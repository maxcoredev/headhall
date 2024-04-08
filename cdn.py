"""
Запускаем всегда вот так:
uvicorn api.media:app --reload --port 5000 --host 192.168.0.101

Во имя науки можно ещё так:
uvicorn api.media:app --reload --port 5000
uvicorn media:app --reload --port 5000
uvicorn media:app --reload --port 5000 --host 192.168.0.101
"""

import io
import os
import datetime
import numpy
from pathlib import Path
from types import SimpleNamespace
from tempfile import SpooledTemporaryFile

from PIL import Image, ImageOps

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.responses import FileResponse, Response
from starlette.routing import Route
from starlette.exceptions import HTTPException
from starlette.datastructures import FormData
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException

from pillow_heif import register_heif_opener, register_avif_opener
register_heif_opener()
register_avif_opener()

DEBUG = True if os.environ.get('DEBUG') == '1' else False
MEDIA_API_KEY = os.environ.get('MEDIA_API_KEY', 'ABC')

MEDIA_RESIZE_VALUE = 2400

KINDS_AND_SIZES = {
    'avatars':        ['600x600', '1200x1200', '240', '72', '96', 'big'],
    'images':         ['600x600', '1200x1200', '240'],
    'comment_images': ['600x600', '1200x1200', '240'],
    'reply_images':   ['600x600', '1200x1200', '240'],
    'pictures': [],
    'comment_pictures': [],
    'reply_pictures': [],
}

Path('files/crops/avatars/big').mkdir(exist_ok=True, parents=True)

for kind in KINDS_AND_SIZES.keys():
    Path(f'files/originals/{kind}').mkdir(exist_ok=True, parents=True)
    Path(f'files/resizes/{kind}').mkdir(exist_ok=True, parents=True)


def check_api_key(func):
    async def proxy(request, *args, **kwargs):
        api_key = request.query_params.get('API_KEY')
        if api_key != MEDIA_API_KEY:
            raise HTTPException(500, 'API_KEY')
        return await func(request, *args, **kwargs)
    return proxy


def image_has_alpha(numpy_image_array):
    """https://stackoverflow.com/a/66649376/4117781"""
    try:
        h, w, c = numpy_image_array.shape
    except ValueError as e:  # Не помню в каких случаях выбрасывается, минимум в 2-х
        h, w, c = (None, None, None)
    return True if c == 4 else False


def add_dash(name):
    return name[:8] + '-' + name[8:]


def get_folders_path(upload_date, folder):
    first_lvl_folders = sorted(os.scandir('files/originals/' + folder), reverse=True, key=lambda f: f.name)
    first_lvl_folder_name = None
    for first_lvl_folder in first_lvl_folders:
        first_lvl_folder_name = first_lvl_folder.path.split('/')[-1].replace('-', '')
        if int(upload_date) < int(first_lvl_folder_name):
            continue
        break

    second_lvl_folders = sorted(os.scandir('files/originals/' + folder + '/' + add_dash(first_lvl_folder_name)), reverse=True, key=lambda f: f.name)
    second_lvl_folder_name = None
    for second_lvl_folder in second_lvl_folders:
        second_lvl_folder_name = second_lvl_folder.path.split('/')[-1].replace('-', '')
        if int(upload_date) < int(second_lvl_folder_name):
            continue
        break

    folders_path = add_dash(first_lvl_folder_name) + '/' + add_dash(second_lvl_folder_name)

    return folders_path


async def put(file, folder):
    new_folder_name = str(int(''.join(file.filename.split('-')[:2])))
    new_folder_name = add_dash(new_folder_name)

    path = 'files/originals/' + folder
    first_lvl_folders = sorted(os.scandir(path), key=lambda f: f.name)

    # Если вообще нет директорий (первый раз за историю что-то заливаем)
    if not len(first_lvl_folders):
        folder_to_upload = path + '/' + new_folder_name + '/' + new_folder_name
        Path(folder_to_upload).mkdir(exist_ok=True, parents=True)
    # Если директории есть
    else:
        first_lvl_last_folder = first_lvl_folders[-1].path
        second_lvl_folders = sorted(os.scandir(first_lvl_last_folder), key=lambda f: f.name)
        second_lvl_folders_files_count = len(list(second_lvl_folders))
        second_lvl_last_folder = second_lvl_folders[-1].path
        second_lvl_last_folder_files_count = len(list(os.scandir(second_lvl_last_folder)))

        # Если директории есть, но файлы не влезают — нужно создать папку
        if second_lvl_last_folder_files_count + 1 > 1000:  # ALARM +1
            # Если на втором уровне упёрлись в лимит — создать ещё одну на первом уровне + первый второй уровень
            if second_lvl_folders_files_count >= 1000:
                folder_to_upload = path + '/' + new_folder_name + '/' + new_folder_name
            # Если на втором уровне ещё не дошли до 1000
            else:
                folder_to_upload = first_lvl_last_folder + '/' + new_folder_name
            Path(folder_to_upload).mkdir(exist_ok=True, parents=True)
        else:
            folder_to_upload = second_lvl_last_folder

    file_bytes = await file.read()
    with Image.open(io.BytesIO(file_bytes)) as image:

        if image.format == 'GIF' or image_has_alpha(numpy.array(image)):
            image = image.convert('RGBA')
            blank_image = Image.new('RGBA', image.size, 'WHITE')
            blank_image.paste(image, mask=image)
            image = blank_image

        w, h = image.size
        if w > MEDIA_RESIZE_VALUE or h > MEDIA_RESIZE_VALUE:
            new_image = ImageOps.contain(image, (MEDIA_RESIZE_VALUE, MEDIA_RESIZE_VALUE), Image.Resampling.LANCZOS)
        else:
            new_image = image

        new_image = new_image.convert('RGB')
        new_image = ImageOps.exif_transpose(new_image)  # Фотографии загруженные с iPhone почему-то перевёрнутые
        new_image = new_image.save(
            folder_to_upload + '/' + file.filename,
            'JPEG',
            subsampling=0,  # https://stackoverflow.com/a/19303889/4117781
            quality=95,
            icc_profile=image.info.get('icc_profile', '')
        )

    file.file.close()

    return new_image


@check_api_key
async def upload(request, folder):
    form = await request.form()
    file = form.get('file')
    new_image = await put(file, folder)
    return Response('OK')


@check_api_key
async def recrop(request):
    form = await request.form()
    old_filename = form.get('old_filename')
    new_filename = form.get('new_filename')

    old_upload_date = ''.join(old_filename.split('-')[:2])
    folders_path = get_folders_path(old_upload_date, 'avatars')
    original_path = 'files/originals/' + 'avatars' + '/' + folders_path + '/' + old_filename

    tempfile = open(original_path, 'rb')
    file = UploadFile(
        file=tempfile,
        filename=new_filename,
    )

    new_image = await put(file, 'avatars')

    return Response('OK')


# @check_api_key  Какой тут нахер API_KEY, это же для пользователей
async def home(request, folder):
    # import time; time.sleep(60.5)

    params = SimpleNamespace()
    params.folder = folder
    params.image_name = request.path_params.get('filename')
    params.width = request.query_params.get('w')
    params.height = request.query_params.get('h')
    params.mins = request.query_params.get('mins')
    params.size = request.query_params.get('size')  # can accept 'big'
    params.crop = params.size or f'{params.width or ""}x{params.height or ""}'
    params.type = 'crops' if params.size else 'resizes'

    if params.width and params.height and (params.mins or params.size):
        raise HTTPException(422, 'too many params')
    elif params.mins and params.mins not in KINDS_AND_SIZES[params.folder]:
        raise HTTPException(422, 'mins not allowed')
    if params.width and params.height and f'{params.width}x{params.height}' not in KINDS_AND_SIZES[params.folder]:
        raise HTTPException(422, 'width and height not allowed')
    elif params.size and params.size not in KINDS_AND_SIZES[params.folder]:
        raise HTTPException(422, 'size not allowed')

    upload_date = ''.join(params.image_name.split('-')[:2])

    folders_path = get_folders_path(upload_date, params.folder)

    original_path = 'files/originals/' + params.folder + '/' + folders_path + '/' + params.image_name
    resize_path = 'files/' + params.type + '/' + params.folder + '/' + params.crop + '/' + folders_path + '/' + params.image_name

    if not params.width and not params.height and not params.size and not params.mins:
        return FileResponse(original_path)

    image = Path(resize_path)
    if image.exists():
        return FileResponse(resize_path)

    if params.size:  # ЕСЛИ ХОТИМ КВАДРАТ
        # На этом этапе:
        # - если бы мы хотели оригинал Авы — мы бы его давно вернули;
        # - если бы мы хотели big или X Авы, который уже есть — мы бы и это вернули;
        # Соответственно:
        # - либо мы хотим сам big, которого нет
        # - либо мы хотим X, и при этом не уверены — есть ли у нас хотя бы big
        # Поэтому:
        # - убедимся что big есть, иначе — создадим его;
        # - если мы big и хотели — вернём его
        # - если мы хотели X — создадим кроп от big-а и вернём его

        big_path = 'files/crops/' + params.folder + '/' + 'big' + '/' + folders_path + '/' + params.image_name
        image = Path(big_path)
        if not image.exists():
            Path(big_path).parent.mkdir(exist_ok=True, parents=True)
            x, y, size = [int(param) for param in params.image_name.split('-')[-2].split('x')]
            crop_box = (x, y, x + size, y + size)

            with Image.open(original_path) as image:
                new_image = image.crop(crop_box)
                new_image = new_image.save(
                    big_path,
                    'JPEG',
                    subsampling=0,  # https://stackoverflow.com/a/19303889/4117781
                    quality=95,  # странно, вроде качество уже резали, а если порезать ещё раз — выйгрыш — 25%
                    icc_profile=image.info.get('icc_profile', '')
                )

        if params.size == 'big':
            return FileResponse(big_path)

        original_path = big_path

    with Image.open(original_path) as image:
        Path(resize_path).parent.mkdir(exist_ok=True, parents=True)
        w, h = image.size
        if params.mins:
            if w < h:
                params.width = params.mins
                params.height = h
            else:
                params.height = params.mins
                params.width = w
        params.w = int(params.width or params.size)
        params.h = int(params.height or params.size)
        if w > params.w or h > params.h:
            new_image = ImageOps.contain(image, (params.w, params.h), Image.Resampling.LANCZOS)
        else:
            new_image = image
        new_image = new_image.save(
            resize_path,
            'JPEG',
            subsampling=0,  # https://stackoverflow.com/a/19303889/4117781
            quality=95,  # странно, вроде качество уже резали, а если порезать ещё раз — выйгрыш — 25%
            icc_profile=image.info.get('icc_profile', '')
        )
        return FileResponse(resize_path)


async def favicon(request):
    return Response('OK')


@check_api_key
async def hello(request):
    # request.path_params.get('username')  # PATH data
    # form = await request.form()  # POST data
    # request.query_params.get('username')  # GET data
    print('Hi, I am GET')
    return Response('Hi, I am GET')


@check_api_key
async def hello_post(request):
    # request.path_params.get('username')  # PATH data
    # form = await request.form()  # POST data
    # request.query_params.get('username')  # GET data
    print('Hi, I am POST')
    return Response('Hi, I am POST')


from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from functools import partial  # https://stackoverflow.com/a/76526037/4117781 (Option 1)

middleware = [
    Middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*']),
    # Middleware(
    #     TrustedHostMiddleware,
    #     allowed_hosts=['*'],
    # ),
    # Middleware(HTTPSRedirectMiddleware)
]

routes = [
    Route('/favicon.ico', favicon),

    Route('/hello',       hello, methods=['GET']),
    Route('/hello/post/', hello_post, methods=['POST']),
]

routes += [
    Route('/avatars/recrop/', partial(recrop), methods=['POST']),
]

for kind in KINDS_AND_SIZES.keys():
    routes += [
        Route(f'/{kind}/upload/',         partial(upload, folder=kind), methods=['POST']),
        Route(f'/{kind}/' + '{filename}', partial(home,   folder=kind), methods=['GET']),
    ]

app = Starlette(routes=routes, middleware=middleware, debug=DEBUG)
