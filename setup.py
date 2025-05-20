from setuptools import setup, find_packages

setup(
    name="leadx",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "requests==2.31.0",
        "aiohttp==3.9.3",
        "pandas==2.2.0",
        "python-dotenv==1.0.1",
        "streamlit==1.31.1",
        "typing-extensions==4.9.0",
        "PyPDF2==3.0.1"
    ],
) 