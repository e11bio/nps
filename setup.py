from setuptools import setup, find_packages

setup(
    name='nps',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[
        'click',
        'volara',
        'pocaduck',
    ],
    entry_points={
        'console_scripts': [
            'nps=nps.main:main',
        ],
    },
    author='Jakob Troidl',
    description='A simple CLI for sampling point clouds from large volumetric datasets',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
    ],
    python_requires='>=3.11',
)
