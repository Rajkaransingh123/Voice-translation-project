import os
import re
import subprocess
import threading
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Video Translator App")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, 'templates'))

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

processing_status = {
    "state": "idle",
    "progress": 0,
    "message": "",
    "current_file": "",
    "output_file": "",
    "target_language": ""
}

LANGUAGE_NAMES = {
    'hi': 'Hindi',
    'mr': 'Marathi',
    'ta': 'Tamil',
    'gu': 'Gujarati',
    'bn': 'Bengali',
    'te': 'Telugu'
}


def secure_filename(filename):
    filename = filename.replace('\\', '/')
    filename = filename.split('/')[-1]
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    return filename or 'file'


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.get('/')
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post('/upload')
async def upload_file(file: UploadFile = File(...), target_language: str = Form('hi')):
    global processing_status

    if not file.filename:
        raise HTTPException(status_code=400, detail='No selected file')

    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail='Invalid file type')

    if processing_status['state'] == 'processing':
        raise HTTPException(status_code=429, detail='System busy processing another file')

    if target_language not in ['hi', 'mr', 'ta', 'gu', 'bn', 'te']:
        raise HTTPException(status_code=400, detail='Invalid target language')

    try:
        filename = secure_filename(file.filename)
        upload_path = os.path.join(UPLOAD_FOLDER, filename)

        contents = await file.read()
        if len(contents) > MAX_CONTENT_LENGTH:
            raise HTTPException(status_code=413, detail='File too large (max 500MB)')

        with open(upload_path, 'wb') as f:
            f.write(contents)

        language_name = LANGUAGE_NAMES.get(target_language, target_language)

        processing_status.update({
            "state": "processing",
            "progress": 0,
            "message": f"Initializing processing for {language_name} translation",
            "current_file": filename,
            "output_file": "",
            "target_language": target_language
        })

        processing_thread = threading.Thread(
            target=process_video,
            args=(upload_path, filename, target_language)
        )
        processing_thread.start()

        return JSONResponse({
            'message': f'File {filename} uploaded successfully for {language_name} translation',
            'filename': filename,
            'target_language': target_language
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def process_video(filepath, original_filename, target_language):
    global processing_status
    base_name = os.path.splitext(os.path.basename(filepath))[0]
    language_name = LANGUAGE_NAMES.get(target_language, target_language)

    try:
        processing_status['message'] = f"Starting video processing for {language_name} translation"

        main_py = os.path.join(BASE_DIR, 'main.py')
        result = subprocess.run(
            ['python', main_py, filepath, target_language],
            capture_output=True,
            text=True,
            cwd=BASE_DIR
        )

        if result.returncode != 0:
            raise Exception(f"Processing failed: {result.stderr}")

        expected_output = os.path.join(BASE_DIR, f"{base_name}_output_video.mp4")
        if not os.path.exists(expected_output):
            raise Exception(f"Output file not generated. main.py output was: {result.stdout}")

        output_filename = f"{base_name}_{language_name}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        os.rename(expected_output, output_path)

        processing_status.update({
            "state": "completed",
            "progress": 100,
            "message": f"Processing completed successfully. {language_name} translation ready!",
            "output_file": output_filename
        })

    except Exception as e:
        processing_status.update({
            "state": "error",
            "message": f"Error: {str(e)}",
            "output_file": ""
        })

    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass


@app.get('/status')
def get_status():
    return JSONResponse(processing_status)


@app.get('/download/{filename}')
def download_file(filename: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_FOLDER, safe_filename)

    if os.path.exists(file_path):
        return FileResponse(file_path, filename=safe_filename)
    return JSONResponse({'error': 'File not found'}, status_code=404)


@app.post('/reset')
def reset_system():
    global processing_status
    processing_status = {
        "state": "idle",
        "progress": 0,
        "message": "",
        "current_file": "",
        "output_file": "",
        "target_language": ""
    }
    return JSONResponse({'message': 'System reset successfully'})


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)