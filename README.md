# Tri-AL: VisuAL ClinicAL TriALs

![Screenshot of platform](screenshot.jpeg)

[Clinicaltrials.gov](https://clinicaltrials.gov) is a website that people all around the world submit the progress and the information of the medical trials on it. Tri-AL is a visualization platform to keep track of clinicaltrials.gov data along with more valuable tools. Tri-AL allows clinicaltrials researchers explore the database in a novel way. It can be used as both standalone project and a baseline for further improvement. It is still under development and we are trying to make it as perfect as possible. 

Setup
------
1. Ensure you are using Python 3.10

2. Install non python requirements: `postgresql``, `shapely`, and `geos`. On Mac with homebrew use `brew install postgresql shapelib geos`

3. Activate environment and install all requirements using pip command and requirements.txt file.
```console
pip install -r requirements.txt
```
4. Update config file by using sample config file. The config file is located in `visual/sample-config.yml`. Name config to `config.yml` in the same directoy. It can be done as following as well:
```console
cp visual/sample-config.yml visual/config.yml
# EDIT config.yml WITH ANY EDITOR
```

5. Intialize database and setting up project.
```console
chmod +x initdb.sh
./initdb.sh
```

6. Download the concent of clinicaltrials.gov from [here](https://clinicaltrials.gov/AllPublicXML.zip) as a zip file to initialize database.

7. Unzip the `AllPublicXML.zip` and place the content under `data` directory in the project root. For example `data/AllPublicXML/`.

8. Import all the XML files to the database.
```console
python3 data_manager.py import -i data/AllPublicXML
```

9. Start project using Django and access it through [browser](http://localhost:8000/admin)!
```console
python3 manage.py runserver
```

Project Structure
------

    .
    ├── panels                  # Internal app for tri-al project that contains core of the server
    │   ├── api                 # Files that are responsible for REST-API to communicate with front-end
    │   └── utils               # Scripts to download and parse clinicaltrials.gov data and insert them into database
    ├── visual                  # Configuration files for Django app
    ├── schedulers              # bash scripts for scheduling tasks such as, updating database
    ├── initdb.sh               # Script to reset the database and make a new one with default values
    ├── httpd.conf              # Backup file of apache configuration for app
    ├── data_manager.py         # Main script to maintain database and download and fill database
    ├── manage.py               # Django script to perform different actions for app
    └── .gitignore

Troubleshooting
------
- This project uses Django 3.3.18 so you need a compatible Python version (e.g. `3.10`)