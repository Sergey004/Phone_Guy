from setuptools import setup, find_packages

setup(
    name="voip_client",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pyaudio",
    ],
    description="A Python library for SIP and RTP VoIP communication",
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/voip_client",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
