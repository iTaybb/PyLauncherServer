import io
import tarfile
from pathlib import Path
import os.path
from typing import Optional, List

import docker

class FileTooBigException(Exception):
    def __init__(self, filename: str, size: int, max_size: int) -> None:
        message = "File {} is {} bytes, (max size is {} bytes)".format(filename, size, max_size)
        super().__init__(message)

        self.filename = filename
        self.size = size
        self.max_size = max_size

def copy_container_to_host(container: docker.models.containers.Container, file: str, dest_path: str, maxsize: int = 0) -> None:
    """
    Copies a file from a container to the host.
    
    dest_path needs to be the destination directory.
    Max size may be limited by maxsize. Value of 0 means there's no limitation.
    """
    stream = io.BytesIO()

    bits, stat = container.get_archive(file)
    if maxsize > 0 and stat['size'] > maxsize:
        raise FileTooBigException(size=stat['size'], max_size=maxsize, filename=stat['name'])
    for chunk in bits:
        stream.write(chunk)
    stream.seek(0)

    with tarfile.TarFile(fileobj=stream) as archive:
        archive.extractall(dest_path)

def copy_host_to_container(container: docker.models.containers.Container, file: str, dest_path: str) -> None:
    """Copies a file or a folder from the host to the container. file may be a source folder or a file."""
    if Path(file).is_dir():
        archive = create_archive(file, arcname=Path(dest_path).name)
        container.put_archive(path=Path(dest_path).parent.as_posix(), data=archive)
    else:
        archive = create_archive(file)
        container.put_archive(path=dest_path, data=archive)

    archive.close()

    with create_archive(file) as archive:
        container.put_archive(path=dest_path, data=archive)

def create_archive(file: str, arcname: Optional[str] = None) -> io.BytesIO:
    """Creates a TAR archive out of a file or a directory."""
    stream = io.BytesIO()

    if not arcname:
        arcname = Path(file).name

    with tarfile.TarFile(fileobj=stream, mode='w') as archive:
        archive.add(file, arcname)
    
    stream.seek(0)
    return stream

def load_tokens(path: str) -> List[str]:
    """Loads the current tokens from file"""
    with open(path, 'r') as f:
        res = [x.strip() for x in f.readlines()]
    return res