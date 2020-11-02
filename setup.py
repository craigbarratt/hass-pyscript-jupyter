"""Create hass_pyscript_kernel package."""

from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='hass_pyscript_kernel',
    version='0.30',
    author='Craig Barratt',
    author_email='@alumni.stanford.edu',
    description='Home Assistant Pyscript Jupyter kernel shim',
    url='https://github.com/craigbarratt/hass-pyscript-jupyter',
    download_url='https://github.com/craigbarratt/hass-pyscript-jupyter/archive/0.30.tar.gz',
    packages=['hass_pyscript_kernel'],
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=[
        'aiohttp',
        'aiohttp_socks',
        'jupyter-client',
        'jupyter-core',
    ],
    python_requires=">=3.7",
    zip_safe=False,
    include_package_data=True,
    package_data={
        "hass_pyscript_kernel": [
            "kernel_files/pyscript.conf",
            "kernel_files/logo-32x32.png",
            "kernel_files/logo-64x64.png"
        ],
    },
    entry_points={
        'console_scripts': [
            'jupyter-pyscript=hass_pyscript_kernel:install_main',
        ],
    },
)
