#!/bin/bash
rm -rf panels/migrations
python manage.py makemigrations panels
python manage.py migrate
python manage.py loaddata panels/fixtures/Country.json
python manage.py createsuperuser