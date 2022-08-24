from django.db.models import fields
from rest_framework import serializers
from panels.models import *



class BiomarkerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Biomarker
        fields = ('name',)



class SponsorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sponsor
        fields = ('name',)



class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ('name', 'type')


class TrialSerializer(serializers.ModelSerializer):
    """
        A class to serialize the Trial objects into json format 
        in order to use it in REST api.
    """

    biomarker_outcome = BiomarkerSerializer(read_only=True, many=True)
    biomarker_entry = BiomarkerSerializer(read_only=True, many=True)
    sponsor = SponsorSerializer(read_only=True, many=True)
    agent = AgentSerializer(read_only=True, many=True)

    location = serializers.CharField(source='get_location_display')
    status = serializers.CharField(source='get_status_display')
    phase = serializers.CharField(source='get_phase_display')
    moa_class = serializers.CharField(source='get_moa_class_display')

    class Meta:
        model = Trial
        # exclude = ('amyloid_sent', 'mmse_sent',)

        fields = ('nct_id',
                    'phase',
                    'title',
                    'location',
                    'status',
                    'repurposed',
                    'start_date',
                    'primary_completion',
                    'biomarker',
                    'sponsor',
                    # testing purpose
                    'agent',
                    'arms_number',
                    'treatment_duration',
                    'title',
                    'study_duration',
        )


class BiomarkerExcelSerializer(serializers.ModelSerializer):
    """
        A class to serialize the trials and their biomarkers 
        in order to write them on an excel file.
    """

    biomarker_outcome = BiomarkerSerializer(read_only=True, many=True)
    biomarker_entry = BiomarkerSerializer(read_only=True, many=True)

    class Meta:
        model = Trial

        fields=('nct_id', 
            'primary_outcome',
            'secondary_outcome',
            'other_outcome',
            'biomarker_outcome',
            'biomarker_entry')


class PipeLineSerializer(serializers.ModelSerializer):
    """
        A serializer in for pipeline data
    """

    biomarker_outcome = BiomarkerSerializer(read_only=True, many=True)
    biomarker_entry = BiomarkerSerializer(read_only=True, many=True)
    sponsor = SponsorSerializer(read_only=True, many=True)
    agent = AgentSerializer(read_only=True, many=True)

    location = serializers.CharField(source='get_location_display')
    status = serializers.CharField(source='get_status_display')
    phase = serializers.CharField(source='get_phase_display')
    moa_class = serializers.CharField(source='get_moa_class_display')
    
    class Meta:
        model = Trial

        fields = ('nct_id',
                    'phase',
                    'title',
                    'location',
                    'status',
                    'moa_class',
                    'repurposed',
                    'start_date',
                    'primary_completion',
                    'biomarker_outcome',
                    'biomarker_entry',
                    'subject_charac',
                    'geography',
                    'moa_subcat',
                    'cadro_moa_cat',
                    'sponsor',
                    'agent',
                    'treatment_duration',
                    'title',
                    'study_duration',
                    'figs_cat',
                    'list_biomarkers',
                    'protocol',
                    'recruitment_period',
                    'treatment_weeks',
                    'treatment_days',
                    'enroll_number',
                    'arms_number',
                    'per_arm',
                    'funder',
                    'mmse',
                    'list_charac',
                    'primary_outcome',
                    'eligibility_criteria',
        )