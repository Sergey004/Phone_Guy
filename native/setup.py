from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import os
import sys

# Get absolute path to pjproject
base_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(base_dir)
pjproject_dir = os.path.join(root_dir, "pjproject")

# Include directories
include_dirs = [
    os.path.join(pjproject_dir, "pjlib", "include"),
    os.path.join(pjproject_dir, "pjlib-util", "include"),
    os.path.join(pjproject_dir, "pjmedia", "include"),
    os.path.join(pjproject_dir, "pjnath", "include"),
    os.path.join(pjproject_dir, "pjsip", "include"),
    os.path.join(pjproject_dir, "pjsip", "include", "pjsua-lib"),
    os.path.join(pjproject_dir, "pjsip", "include", "pjsua2"),
    base_dir,
]

# Library directories
lib_dirs = [
    os.path.join(pjproject_dir, "pjlib", "lib"),
    os.path.join(pjproject_dir, "pjlib-util", "lib"),
    os.path.join(pjproject_dir, "pjnath", "lib"),
    os.path.join(pjproject_dir, "pjmedia", "lib"),
    os.path.join(pjproject_dir, "pjsip", "lib"),
]

ext = Extension(
    name="_pcm_media",
    sources=[
        os.path.join(base_dir, "bindings.i"),
        os.path.join(base_dir, "pcm_media.cpp"),
    ],
    include_dirs=include_dirs,
    library_dirs=lib_dirs,
    libraries=[
        "pjsua2",
        "pjsua",
        "pjmedia",
        "pjmedia-codec",
        "pjmedia-audiodev",
        "pjnath",
        "pjlib-util",
        "pj",
    ],
    runtime_library_dirs=[
        "$ORIGIN/../pjproject/pjlib/lib",
        "$ORIGIN/../pjproject/pjlib-util/lib",
        "$ORIGIN/../pjproject/pjmedia/lib",
        "$ORIGIN/../pjproject/pjnath/lib",
        "$ORIGIN/../pjproject/pjsip/lib",
    ],
    extra_compile_args=[
        "-std=c++11",
        "-fPIC",
        "-Wno-write-strings",
        "-Wno-deprecated-declarations",
    ] + [f"-I{d}" for d in include_dirs],
    swig_opts=[
        "-c++",
        "-Wall",
    ] + [f"-I{d}" for d in include_dirs],
    language="c++",
)

setup(
    name="pcm_media",
    version="0.1.0",
    description="PCM audio media port for PJSUA2",
    author="PhoneGuy Bot",
    py_modules=["pcm_media"],
    ext_modules=[ext],
    zip_safe=False,
)
