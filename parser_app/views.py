from django.shortcuts import render
from django.conf import settings
from .forms import UploadFileForm
from .utils import process_excel_file
import os
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import pandas as pd
import logging

def upload_view(request):
    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                col_mapping = {
                    'street_col': form.cleaned_data['street_col'],
                    'unit_col': form.cleaned_data['unit_col'],
                    'city_col': form.cleaned_data['city_col'],
                    'state_col': form.cleaned_data['state_col'],
                    'zip_col': form.cleaned_data['zip_col'],
                }
                
                output_filename, plot_image, stats = process_excel_file(
                    request.FILES['file'], 
                    col_mapping
                )
                
                context = {
                    'stats': stats,
                    'plot_image': plot_image,
                    'download_url': f"{settings.MEDIA_URL}{output_filename}"
                }
                return render(request, 'parser_app/results.html', context)
            except Exception as e:
                form.add_error(None, f"Processing Error: {str(e)}")
    else:
        form = UploadFileForm()
    
    return render(request, 'parser_app/upload.html', {'form': form})

@require_POST
def preview_excel(request):
    """
    Accepts an Excel file via POST and returns a JSON response
    with the headers and the first 5 rows of data for preview.
    """
    if 'file' not in request.FILES:
        return JsonResponse({'error': 'No file uploaded.'}, status=400)

    file_obj = request.FILES['file']
    
    if not file_obj.name.endswith(('.xls', '.xlsx')):
        return JsonResponse({'error': 'Invalid file type. Please upload an Excel file (.xls, .xlsx).'}, status=400)

    try:
        # Read only the first 5 rows for preview
        df = pd.read_excel(file_obj, nrows=5)
        
        # Replace NaN with an empty string for better JSON and frontend representation
        df = df.fillna('')

        headers = df.columns.tolist()
        rows = df.values.tolist()
        
        return JsonResponse({'headers': headers, 'rows': rows})
    except Exception as e:
        logging.error(f"Excel preview failed for file '{file_obj.name}': {e}", exc_info=True)
        return JsonResponse({'error': 'Could not read the file. Please ensure it is a valid Excel file.'}, status=400)
