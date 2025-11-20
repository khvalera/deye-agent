from setuptools import setup, find_packages
import os

def find_mo_files():
    mo_files = []
    for root, dirs, files in os.walk("deye_agent/locale"):
        for file in files:
            if file.endswith(".mo"):
                filepath = os.path.relpath(os.path.join(root, file), "deye_agent")
                mo_files.append(filepath)
    return mo_files

setup(
    name="deye-agent",
    version="0.1.0",
    description="Deye Agent — tool for retrieving data from Deye inverter and sending notifications",
    author="khvalera@ukr.net",
    author_email="khvalera@ukr.net",
    url="https://github.com/khvalera/deye-agent",
    packages=find_packages(),
    python_requires='>=3.6',
    install_requires=[
        "PyYAML>=5.3.1",
        "paho-mqtt>=1.5.0",
        "chardet>=3.0.4",
        "idna>=2.5",
    ],
    package_data={
        'deye_agent': find_mo_files(),
    },
    entry_points={
        'console_scripts': [
            'deye-agent=deye_agent.cli:main',
        ],
    },
    license='Apache License 2.0',
    classifiers=[
        "Programming Language :: Python :: 3",
        'License :: OSI Approved :: Apache Software License',
        "Operating System :: OS Independent",
    ],
)
