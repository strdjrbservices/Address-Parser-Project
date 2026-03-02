from django.shortcuts import render, redirect
from django.conf import settings
from .forms import UploadFileForm
from .utils import process_excel_file, TaskCanceledException
import os
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage
from django.urls import reverse
from django.contrib import messages
import uuid
import threading
import pandas as pd
import logging

def upload_view(request):
    """
    Handles GET requests to display the file upload form.
    POST logic is now handled by start_processing_view via AJAX.
    """
    form = UploadFileForm()
    return render(request, 'parser_app/upload.html', {'form': form})

@require_POST
def start_processing_view(request):
    """
    Starts the file processing task in a background thread.
    """
    form = UploadFileForm(request.POST, request.FILES)
    if form.is_valid():
        file = request.FILES['file']
        fs = FileSystemStorage()
        temp_filename = fs.save(file.name, file)
        
        col_mapping = {
            'street_col': form.cleaned_data['street_col'],
            'unit_col': form.cleaned_data['unit_col'],
            'city_col': form.cleaned_data['city_col'],
            'state_col': form.cleaned_data['state_col'],
            'zip_col': form.cleaned_data['zip_col'],
        }

        task_id = uuid.uuid4().hex
        
        thread = threading.Thread(
            target=run_processing_task, 
            args=(task_id, temp_filename, col_mapping)
        )
        thread.start()
        
        return JsonResponse({'task_id': task_id})
    else:
        return JsonResponse({'error': 'Invalid form submission.', 'errors': form.errors.as_json()}, status=400)

def run_processing_task(task_id, temp_filename, col_mapping):
    """
    The actual function that runs in the background, processes the file,
    and stores the result in the cache.
    """
    fs = FileSystemStorage()
    try:
        cache.set(f'{task_id}_cancel_requested', False, timeout=3600) # Ensure flag is reset
        cache.set(f'{task_id}_progress', {'state': 'PENDING', 'progress': 0, 'details': 'Starting...'}, timeout=3600)
        
        with fs.open(temp_filename) as file_obj:
            output_filename, plot_image, stats = process_excel_file(
                file_obj, 
                col_mapping,
                task_id=task_id
            )
        
        result_data = {
            'stats': stats,
            'plot_image': plot_image,
            'download_url': f"{settings.MEDIA_URL}{output_filename}"
        }
        cache.set(f'{task_id}_result', result_data, timeout=3600)
        cache.set(f'{task_id}_progress', {'state': 'SUCCESS'}, timeout=3600)

    except TaskCanceledException:
        logging.info(f"Task {task_id} was canceled by user.")
        cache.set(f'{task_id}_progress', {'state': 'CANCELED', 'details': 'Processing was canceled by the user.'}, timeout=3600)
    except Exception as e:
        logging.error(f"Task {task_id} failed: {e}", exc_info=True)
        cache.set(f'{task_id}_progress', {'state': 'FAILURE', 'details': str(e)}, timeout=3600)
    finally:
        if fs.exists(temp_filename):
            fs.delete(temp_filename)

def get_progress_view(request, task_id):
    """
    Called by the frontend to get progress updates for a task.
    """
    progress_data = cache.get(f'{task_id}_progress')
    if progress_data:
        if progress_data['state'] == 'SUCCESS':
            return JsonResponse({
                'state': 'SUCCESS',
                'url': reverse('results', kwargs={'task_id': task_id})
            })
        return JsonResponse(progress_data)
    return JsonResponse({'state': 'PENDING', 'details': 'Waiting for task to start...'})

def results_view(request, task_id):
    """
    Displays the final results page for a completed task.
    """
    result_data = cache.get(f'{task_id}_result')
    if not result_data:
        messages.error(request, 'The results for this task have expired or could not be found. Please try uploading again.')
        return redirect('upload')
    
    return render(request, 'parser_app/results.html', result_data)

@require_POST
def cancel_processing_view(request, task_id):
    """
    Sets a flag in the cache to signal the background task to cancel.
    """
    cache.set(f'{task_id}_cancel_requested', True, timeout=3600)
    return JsonResponse({'status': 'cancellation_requested'})

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
        
        # Convert all data to string to ensure JSON serializability (e.g. for Dates)
        df = df.astype(str)

        headers = df.columns.tolist()
        rows = df.values.tolist()
        
        return JsonResponse({'headers': headers, 'rows': rows})
    except Exception as e:
        logging.error(f"Excel preview failed for file '{file_obj.name}': {e}", exc_info=True)
        return JsonResponse({'error': 'Could not read the file. Please ensure it is a valid Excel file.'}, status=400)
