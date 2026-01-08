from setuptools import setup, Extension
import os

# Get absolute path to pjproject
base_dir = os.path.dirname(os.path.abspath(__file__))
pjproject_include = os.path.join(os.path.dirname(base_dir), "pjproject", "pjsip", "include")
pjproject_lib = os.path.join(os.path.dirname(base_dir), "pjproject")
pjlib_lib = os.path.join(pjproject_lib, "pjlib", "lib")
pjlib_util_lib = os.path.join(pjproject_lib, "pjlib-util", "lib")
pjnath_lib = os.path.join(pjproject_lib, "pjnath", "lib")
pjmedia_lib = os.path.join(pjproject_lib, "pjmedia", "lib")
pjsip_lib = os.path.join(pjproject_lib, "pjsip", "lib")
pjlib_util_include = os.path.join(os.path.dirname(base_dir), "pjproject", "pjlib-util", "include")
pjmedia_include = os.path.join(os.path.dirname(base_dir), "pjproject", "pjmedia", "include")
pjnath_include = os.path.join(os.path.dirname(base_dir), "pjproject", "pjnath", "include")
pjlib_include = os.path.join(os.path.dirname(base_dir), "pjproject", "pjlib", "include")

ext = Extension(
    name="pcm_media",
    sources=[
        "bindings.i",
        "pcm_media.cpp",
    ],
    include_dirs=[
        "pjproject/pjlib/include",
        "pjproject/pjlib-util/include",
        "pjproject/pjmedia/include",
        "pjproject/pjnath/include",
        "pjproject/pjsip/include",
        "pjproject/pjsip/include/pjsua-lib",
        "pjproject/pjsip/include/pjsua2",
        "native",
    ],
    library_dirs=[
        pjlib_lib,
        pjlib_util_lib,
        pjnath_lib,
        pjmedia_lib,
        pjsip_lib,
    ],
    libraries=[
        "pjsua2", "pjsua", "pjmedia", "pjmedia-codec", "pjmedia-audiodev", 
        "pjnath", "pjlib-util", "pj"
    ],
    runtime_library_dirs=[
        "$ORIGIN/../pjproject/pjlib/lib",
        "$ORIGIN/../pjproject/pjmedia/lib",
        "$ORIGIN/../pjproject/pjsip/lib",
    ],
    extra_compile_args=[
        f"-I{pjproject_include}",
        f"-I{pjlib_include}",
        f"-I{pjlib_util_include}",
        f"-I{pjmedia_include}",
        f"-I{pjnath_include}",
    ],
    swig_opts=["-c++", 
               "-interface", "pcm_media",
               f"-I{pjproject_include}",
               "-I pjproject/pjlib/include", 
               "-I pjproject/pjlib-util/include", 
               "-I pjproject/pjmedia/include", 
               "-I pjproject/pjsip/include", 
               "-I pjproject/pjsip/include/pjsua-lib", 
               "-I pjproject/pjsip/include/pjsua2", 
               "-I pjproject/pjnath/include"],
    language="c++",
)

setup(
    name="pcm_media",
    version="0.1",
    ext_modules=[ext],
)
