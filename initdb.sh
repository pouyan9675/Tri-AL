#!/bin/bash
rm -r panels/migrations
python3 manage.py makemigrations panels
python3 manage.py migrate
python3 manage.py loaddata panels/fixtures/Country.json
python3 manage.py createsuperuser