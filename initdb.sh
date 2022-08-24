#!/bin/bash
rm -r panels/migrations
./manage.py makemigrations panels
./manage.py migrate
./manage.py loaddata panels/fixtures/Country.json
./manage.py loaddata panels/fixtures/Funder.json
./data_manager.py cleanfill
./manage.py createsuperuser