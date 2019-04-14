#!/usr/bin/env python3

import os.path
from functools import wraps
import tempfile
import base64
import docker
import re
import urllib3
from pathlib import Path
import json
import traceback
from typing import Callable, Tuple

from flask import Flask, jsonify, request, abort
import requests.exceptions

import utils

__version__ = "2019.04.14"

app = Flask(__name__)
application = app  # Elastic Beanstalk looks for the "application" WGSI app.

LANGS = {
    # 'langname': 'docker-image-name',
    'py37': 'python:3.7-slim',
    'py36': 'python:3.6-slim',
    'py35': 'python:3.5-slim',
    'py27': 'python:2.7-slim'
}
BASE64_REGEX = re.compile(r'^[a-zA-Z0-9+/]+={0,2}$')
FILENAME_REGEX = re.compile(r'^[\w,\s-]+\.[A-Za-z]{1,4}$')
MAX_REQUEST_SIZE = 1 * 1024 * 1024   # 1MB
MAX_EXECUTION_LIMIT = 60  # in seconds
MAX_OUTPUT_FILESIZE = 4 * 1024 * 1024  # 4MB
CONTAINER_WORKING_DIR = '/usr/src/app'
FORMATS = ['text', 'base64_encoded_binary', 'json']
DIR_PATH = os.path.dirname(os.path.realpath(__file__))
CODE_PATH = os.path.dirname(os.path.realpath(__file__))

TOKENS_FILE = os.path.join(DIR_PATH, 'tokens.txt')
TOKENS = utils.load_tokens(TOKENS_FILE)

def limit_content_length(max_length: int) -> Callable:
    """Limits a request to max_length bytes at max."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cl = request.content_length
            if cl is not None and cl > max_length:
                abort(413)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def die(reason: str = "Fatal Error. Please contact the service's operators and consult for support.", returncode: int = 400) -> Tuple[str, int]:
    """Returns a json of an error."""
    return jsonify({
        "success": False,
        "errorMsg": reason
    }), returncode

@app.route("/params", methods=['GET'])
def parameters():
    return jsonify({
        "types": list(LANGS.keys()),
        "formats": FORMATS,
        "version": __version__
    }), 200

@app.route("/exec/<lang>", methods=['POST'])
@limit_content_length(MAX_REQUEST_SIZE)
def exec(lang):
    # Input validation checks
    if not request.is_json:
        return die('Payload is not valid JSON.')

    req = request.get_json()

    if not req or not req.get('code'):
        return die("Payload is empty.")

    if not req.get('token'):
        return die("Request is missing a token.")

    if req['token'] not in TOKENS:
        return die("Token {} is invalid.".format(req['token']))

    if not BASE64_REGEX.match(req['code']):
        return die("Code is not valid Base64 Encoding (RFC 3548).")
    
    if 'output_file' in req and not FILENAME_REGEX.match(req['output_file']):
        return die("Output filename is not allowed. Use a valid filename.")

    if lang not in LANGS:
        return die("Language {} is not supported. Supported languages are: {}.".format(lang, ", ".join(LANGS)))

    if req.get('output_file_type') not in ['text', 'base64_encoded_binary', 'json', None]:
        return die("output_file_type {} is not supported. Supported values are: text, base64_encoded_binary, json, or blank (defaulting to base64_encoded_binary).".format(req.get('output_file_type')))

    # Executing the code
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, 'run.py'), 'wb') as f:
            f.write(base64.b64decode(req['code']))
        with open(os.path.join(tmpdir, 'requirements.txt'), 'w') as f:
            f.write(req.get('requirements', ''))

        dockerClient = docker.from_env()
        try:
            container = dockerClient.containers.run(image=LANGS[lang], command='sh -c "pip install -qqq --no-cache-dir -r requirements.txt && python run.py"', auto_remove=False, working_dir=CONTAINER_WORKING_DIR, stderr=True, detach=True)
            utils.copy_host_to_container(container, tmpdir, CONTAINER_WORKING_DIR)
            container.start()
            res = container.wait(timeout=MAX_EXECUTION_LIMIT)
            stdout = container.logs(stdout=True, stderr=False)
            stderr = container.logs(stdout=False, stderr=True)

            output_file_payload = ''
            if res['StatusCode'] == 0 and 'output_file' in req:
                utils.copy_container_to_host(container, Path(CONTAINER_WORKING_DIR).joinpath(req['output_file']).as_posix(), tmpdir, maxsize=MAX_OUTPUT_FILESIZE)
                type_ = req.get('output_file_type', 'base64_encoded_binary')
                if type_ == 'text':
                    with open(os.path.join(tmpdir, req['output_file'])) as f:
                        output_file_payload = f.read()
                elif type_ == 'json':
                    with open(os.path.join(tmpdir, req['output_file'])) as f:
                        output_file_payload = json.loads(f.read())
                elif type_ == 'base64_encoded_binary':
                    with open(os.path.join(tmpdir, req['output_file']), 'rb') as f:
                        output_file_payload = base64.b64encode(f.read()).decode('utf-8', "replace").strip()
                else:
                    pass  # should never happen
        except json.JSONDecodeError as e:
            return die("Output file could not be parsed as valid JSON: {}".format(str(e)))
        except requests.exceptions.ConnectionError as e:
            if [x for x in e.args if isinstance(x, urllib3.exceptions.ReadTimeoutError)]:  # if timeout
                return die("Execution time has passed the limit of {} seconds.".format(MAX_EXECUTION_LIMIT))
            else:
                return die()
        except (docker.errors.NotFound, utils.FileTooBigException) as e:
            return die(str(e))
        except docker.errors.DockerException as e:
            return die(returncode=500)
        finally:
            # cleanup
            try:
                container.remove(force=True)
            except: pass
        
    # Returning the command
    isSuccess = res['StatusCode'] == 0
    http_code = 200 if isSuccess else 400
    
    return jsonify({
        "success": isSuccess,
        "exit_code": res['StatusCode'],
        "stdout": stdout.decode('utf-8', "replace").strip() if stdout else "",
        "stderr": stderr.decode('utf-8', "replace").strip() if stderr else "",
        "output": output_file_payload,
        "output_format": req.get('output_file_type', 'base64_encoded_binary')
    }), http_code

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")
    
