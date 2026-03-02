import pandas as pd
import re
import psutil
import usaddress
import matplotlib
matplotlib.use('Agg') # Use non-interactive backend for server
import matplotlib.pyplot as plt
import io
import base64
import os
from django.conf import settings
from deepparse.parser import AddressParser
from django.core.cache import cache

class TaskCanceledException(Exception):
    """Custom exception for canceled tasks."""
    pass

# Initialize model once at module level to save time on requests
def get_best_model():
    total_ram = psutil.virtual_memory().total / (1024**3)
    if total_ram > 12:
        return "fasttext"
    elif total_ram >= 8:
        return "fasttext-light"
    else:
        return "bpemb"
    
MODEL_TYPE = get_best_model()
print(f"Selected model based on RAM: {MODEL_TYPE}")
# Initialize lazily or on import. 
# Note: In production, this consumes memory per worker.
try:
    address_parser_model = AddressParser(model_type=MODEL_TYPE, device="cpu")
except Exception as e:
    print(f"Error initializing DeepParse: {e}")
    address_parser_model = None

def clean_addresses(df, address_col):
    def split_dual_addresses(addr):
        if isinstance(addr, str):
            match = re.match(r'^(\d+)\s*[-,\/]\s*(\d+)\s+(.*)', addr)
            if match:
                num1, num2, rest = match.groups()
                return [f"{num1} {rest}", f"{num2} {rest}"]
        return [addr]

    df[address_col] = df[address_col].apply(split_dual_addresses)
    df = df.explode(address_col).reset_index(drop=True)

    def apply_cleaning(addr):
        if not isinstance(addr, str):
            return addr
        addr = re.sub(r'^(\d+)\s+\1', r'\1', addr)
        addr = re.sub(r'\b(ST|AVE|BLVD|RD|LN|DR|CT|WAY)\.?\s+\1\b', r'\1', addr, flags=re.IGNORECASE)
        addr = re.sub(r'\s+([A-Z]|\d+)$', r' #\1', addr)
        return addr.strip()

    df[address_col] = df[address_col].apply(apply_cleaning)
    return df

def process_excel_file(file_obj, col_mapping, task_id=None):
    # Load Data
    df = pd.read_excel(file_obj)
    
    street_col = col_mapping.get('street_col')
    unit_col = col_mapping.get('unit_col')
    city_col = col_mapping.get('city_col')
    state_col = col_mapping.get('state_col')
    zip_col = col_mapping.get('zip_col')

    if street_col not in df.columns:
        raise ValueError(f"Column '{street_col}' not found in Excel file.")

    # Clean
    df = clean_addresses(df, street_col)
    
    parsed_rows = []
    failed_rows = []
    total_rows = len(df)

    for index, row in df.iterrows():
        # --- Progress & Cancellation Check ---
        if task_id:
            # Update progress and check for cancellation every 20 rows
            if (index + 1) % 20 == 0:
                if cache.get(f'{task_id}_cancel_requested'):
                    raise TaskCanceledException("Task canceled by user.")
                
                progress = int(((index + 1) / total_rows) * 100)
                cache.set(f'{task_id}_progress', {
                    'state': 'PROCESSING',
                    'progress': progress,
                    'details': f'Processed {index + 1} of {total_rows} rows'
                }, timeout=3600)
        # --------------------------

        address_str = row[street_col]
        if pd.isna(address_str):
            continue
        
        address_str = str(address_str)
        parser_used = 'failed'
        
        # Logic from your script
        try:
            parsed_address = address_parser_model(address_str)
            if not parsed_address or not parsed_address.StreetName:
                raise ValueError("Incomplete parse: StreetName not found.")

            address_line_1_parts = [
                parsed_address.StreetNumber,
                parsed_address.Orientation,
                parsed_address.StreetName
            ]
            address_line_1 = " ".join(part for part in address_line_1_parts if part).strip()
            
            parsed_unit = parsed_address.Unit or ""
            parsed_city = parsed_address.Municipality or ""
            parsed_state = parsed_address.Province or ""
            parsed_zip = parsed_address.PostalCode or ""
            parser_used = 'deepparse'

        except Exception as e:
            try:
                parsed_data, _ = usaddress.tag(address_str)
                address_line_1_parts = [
                    parsed_data.get("AddressNumber", ""),
                    parsed_data.get("StreetNamePreDirectional", ""),
                    parsed_data.get("StreetName", ""),
                    parsed_data.get("StreetNamePostType", ""),
                    parsed_data.get("StreetNamePostDirectional", "")
                ]
                address_line_1 = " ".join(part for part in address_line_1_parts if part).strip()
                parsed_unit = " ".join([parsed_data.get("OccupancyType", ""), parsed_data.get("OccupancyIdentifier", "")]).strip()
                parsed_city = parsed_data.get("PlaceName", "")
                parsed_state = parsed_data.get("StateName", "")
                parsed_zip = parsed_data.get("ZipCode", "")
                parser_used = 'usaddress'
            except Exception as fallback_e:
                failed_rows.append({'Original Address': address_str, 'Error': str(e)})
                address_line_1 = address_str
                parsed_unit, parsed_city, parsed_state, parsed_zip = "", "", "", ""

        # Final values
        final_address_line_2 = str(row[unit_col]).strip() if unit_col and unit_col in df.columns and pd.notna(row[unit_col]) else parsed_unit
        final_city = str(row[city_col]).strip() if city_col and city_col in df.columns and pd.notna(row[city_col]) else parsed_city
        final_state = str(row[state_col]).strip() if state_col and state_col in df.columns and pd.notna(row[state_col]) else parsed_state
        final_zip = str(row[zip_col]).strip() if zip_col and zip_col in df.columns and pd.notna(row[zip_col]) else parsed_zip

        parsed_rows.append([address_line_1, final_address_line_2, final_city, final_state, final_zip, parser_used])

    # Create Result DataFrame
    clean_df = pd.DataFrame(parsed_rows, columns=["AddressLine1", "AddressLine2", "City", "State", "Zip Code", "ParserUsed"])
    
    # Save to Media
    base_name = os.path.basename(str(file_obj.name))
    output_filename = f"Cleaned_{base_name}"
    output_path = os.path.join(settings.MEDIA_ROOT, output_filename)
    clean_df.to_excel(output_path, index=False)

    # Generate Plot
    deepparse_count = len(clean_df[clean_df['ParserUsed'] == 'deepparse'])
    usaddress_count = len(clean_df[clean_df['ParserUsed'] == 'usaddress'])
    failed_count = len(failed_rows)
    
    labels = ['DeepParse', 'UsAddress', 'Failed']
    sizes = [deepparse_count, usaddress_count, failed_count]
    colors = ['#4CAF50', '#2196F3', '#F44336']
    explode = (0, 0, 0.1)

    plt.figure(figsize=(6, 4))
    # Filter out 0 sizes to avoid matplotlib errors/ugly charts
    valid_indices = [i for i, x in enumerate(sizes) if x > 0]
    if valid_indices:
        plt.pie([sizes[i] for i in valid_indices], 
                explode=[explode[i] for i in valid_indices], 
                labels=[labels[i] for i in valid_indices], 
                colors=[colors[i] for i in valid_indices], 
                autopct='%1.1f%%', startangle=140)
    else:
        plt.text(0.5, 0.5, 'No Data', ha='center')
        
    plt.title('Address Parsing Breakdown')
    plt.axis('equal')
    
    # Save plot to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close()

    stats = {
        'total': len(df),
        'success': len(df) - failed_count,
        'deepparse': deepparse_count,
        'usaddress': usaddress_count,
        'failed': failed_count,
        'model_type': MODEL_TYPE
    }

    return output_filename, image_base64, stats
