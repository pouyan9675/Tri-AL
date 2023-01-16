from simple_history.models import HistoricalRecords
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from panels.utils import downloader, customize
from visual import settings



class Agent(models.Model):
    name = models.TextField()
    other_names = models.TextField()
    
    COMBINATION = '0'
    DEVICE = '1'
    BIOLOGICAL = '2'
    RADIATION = '3'
    OTHER = '4'
    GENETIC = '5'
    DRUG = '6'
    PROCEDURE = '7'
    DIETARY = '8'
    DIAGNOSTIC = '9'
    BEHAVIORAL = '10'
    AGENT_TYPE_CHOICES = [
        (COMBINATION, 'Combination Product'),
        (DEVICE, 'Device'),
        (BIOLOGICAL, 'Biological'),
        (RADIATION, 'Radiation'),
        (OTHER, 'Other'),
        (GENETIC, 'Genetic'),
        (DRUG, 'Drug'),
        (PROCEDURE, 'Procedure'),
        (DIETARY, 'Dietary Supplement'),
        (DIAGNOSTIC, 'Diagnostic Test'),
        (BEHAVIORAL, 'Behavioral'),
    ]
    type = models.CharField(max_length=2, choices=AGENT_TYPE_CHOICES)


    def __str__(self):
        return self.name


    def get_type_choice(str_type):
        for i, name in Agent.AGENT_TYPE_CHOICES:
            if str_type == name:
                return i
        
        return None



class Condition(models.Model):
    name = models.TextField()
    other_name = models.TextField()


    def __str__(self):
        return self.name



class Biomarker(models.Model):

    class Meta:
        verbose_name = 'Biomarker'
        verbose_name_plural = 'Biomarkers'

    name = models.CharField(max_length=50)
    type = models.CharField(max_length=1, null=True)

    def __str__(self):
        return self.name



class Sponsor(models.Model):
    name = models.TextField()

    class Meta:
        verbose_name = 'Sponsor'
        verbose_name_plural = 'Sponsors'

    def __str__(self):
        return self.name



class Country(models.Model):
    name = models.TextField()
    alpha3 = models.CharField(max_length=3)
    alpha2 = models.CharField(max_length=2)

    def __str__(self):
        return self.name



class Trial(models.Model):
    """
        Saving Alzheimer's trials in database with required fields
    """
    nct_id = models.CharField(max_length=11, unique=True, verbose_name='NCT ID')

    NOPHASE = 'N'
    EARLY1 = 'E'
    PHASE1 = '1'
    PHASE2 = '2'
    PHASE3 = '3'
    PHASE12 = '12'
    PHASE23 = '23'
    PHASE4 = '4'
    PHASE_CHOICES = [
        (NOPHASE, 'No Phase'),
        (EARLY1, 'Early 1'),
        (PHASE1, 'Phase 1'),
        (PHASE2, 'Phase 2'),
        (PHASE3, 'Phase 3'),
        (PHASE12, 'Phase 1 | Phase 2'),
        (PHASE23, 'Phase 2 | Phase 3'),
        (PHASE4, 'Phase 4'),
    ]
    phase = models.CharField(max_length=2, choices=PHASE_CHOICES, blank=True)

    ACTIVE = 'A'
    COMPLETED = 'C'
    ENROLLING = 'E'
    NOT_YET = 'N'
    RECRUITING = 'R'
    SUSPENDED = 'S'
    TERMINATED = 'T'
    UNKNOWN = 'U'
    WITHDRAWN = 'W'
    STATUS_CHOICES = [
        (ACTIVE, 'Active, not recruiting'),
        (COMPLETED, 'Completed'),
        (ENROLLING, 'Enrolling by invitation'),
        (NOT_YET, 'Not yet recruiting'),
        (RECRUITING, 'Recruiting'),
        (SUSPENDED, 'Suspended'),
        (TERMINATED, 'Terminated'),
        (UNKNOWN, 'Unknown status'),
        (WITHDRAWN, 'Withdrawn'),
    ]
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)
    
    
    TREATMENT = 'T'
    PREVENTION = 'P'
    DIAGNOSTIC = 'D'
    SUPPORTIVE_CARE = 'U'
    SCREENING = 'C'
    HEALTH_SERVICE = 'H'
    BASIC_SCIENCE = 'B'
    OTHER = 'O'
    PURPOSE_CHOICES = [
        (TREATMENT, 'Treatment'),
        (PREVENTION, 'Prevention'),
        (DIAGNOSTIC, 'Diagnostic'),
        (SUPPORTIVE_CARE, 'Supportive Care'),
        (SCREENING, 'Screening'),
        (HEALTH_SERVICE, 'Health Services Research'),
        (BASIC_SCIENCE, 'Basic Science'),
        (OTHER, 'Other'),
    ]
    design_primary_purpose = models.CharField(max_length=1, choices=PURPOSE_CHOICES, null=True)

    agent = models.ManyToManyField(Agent, blank=True, verbose_name='Agents')
    condition = models.ManyToManyField(Condition, blank=True, verbose_name='Conditions/Diseases')
    protocol = models.CharField(max_length=50, null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    first_posted = models.DateField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    first_start_date = models.DateField(null=True, blank=True, verbose_name='Start Date at First Registration')
    end_date = models.DateField(null=True, blank=True)
    first_end_date = models.DateField(null=True, blank=True, verbose_name='End Date at First Registration')
    primary_completion = models.DateField(null=True, blank=True)
    first_primary_completion = models.DateField(null=True, blank=True, verbose_name='Primary Completion Date at First Registration')
    last_update = models.DateField(null=True, blank=True)
    study_duration = models.IntegerField(null=True, blank=True)
    primary_outcome = models.TextField(null=True, blank=True, verbose_name='Primary Outcome Measure')
    secondary_outcome = models.TextField(null=True, blank=True, verbose_name='Secondary Outcome Measures')
    other_outcome = models.TextField(null=True, blank=True, verbose_name='Other Outcome Measures')
    eligibility_criteria = models.TextField(null=True, blank=True)
    treatment_duration = models.CharField(max_length=500, null=True, blank=True)
    treatment_weeks = models.FloatField(null=True, blank=True)
    treatment_days = models.IntegerField(null=True, blank=True)
    enroll_number = models.IntegerField(null=True, blank=True)
    arms_number = models.IntegerField(null=True, blank=True)
    per_arm = models.IntegerField(null=True, blank=True)
    sponsor = models.ManyToManyField(Sponsor, blank=True, verbose_name='Sponsors')

    NIH = 'N'
    FED = 'F'
    INDUSTRY = 'I'
    OTHER_GOV = 'G'
    OTHER = 'O'
    FUNDER_CHOICES = [
        (NIH, 'U.S. National Institutes of Health'),
        (FED, 'Federal Agencies'),
        (INDUSTRY, 'Industry'),
        (OTHER_GOV, 'Other_Gov'),
        (OTHER, 'Other'),
    ]
    funder_type = models.CharField(max_length=1, choices=FUNDER_CHOICES, null=True)

    US = '1'
    NONUS = '2'
    BOTH = '3'
    LOCATION_CHOICES = [
        (US, 'US ONLY'),
        (NONUS, 'NON-US ONLY'),
        (BOTH, 'BOTH US & NON-US'),
    ]
    location = models.CharField(max_length=1, choices=LOCATION_CHOICES, null=True, blank=True)
    countries = models.ManyToManyField(Country, blank=True, verbose_name='Countries')
    
    location_str = models.TextField(null=True, blank=True, verbose_name='Locations')
    num_sites = models.IntegerField(null=True, blank=True)
    min_age = models.CharField(max_length=11, blank=True, null=True)
    max_age = models.CharField(max_length=11, blank=True, null=True)
    biomarker = models.ManyToManyField(Biomarker, blank=True, verbose_name='Biomarkers')
    description = models.TextField(null=True)
    brief_summary = models.TextField(null=True)
    
    # system variables
    reviewed = models.BooleanField(default=False)
    history = HistoricalRecords()

    # adding user defined columns
    vars().update(customize.Database.columns)



    def __str__(self):
        return self.nct_id


    def save(self, *args, **kwargs):
        """
            Applying preprocess and filling some fields automatically
            based on given values
        """

        if self.location == 0:
            self.location_symbol(self.geography)


        super(Trial, self).save(*args, **kwargs)
        


    @staticmethod
    def location_symbol(x : str) -> str:
        """
        Checks if a given location is US or NON-US and returns
        related symbol to store it in database. In order to
        better readibilty it is written as a fucntion instead
        of lambda form.

        - Parameters
        ============================
        + x:    String of geography column

        - Return
        ============================
        + str: Related character for US or NON-US in database
        """
        x = str(x)
        if not x:
            return ''
        
        us = False
        countries = set([c.split(',')[-1].strip() for c in x.split('\n')])
        if "United States" in x or "Canada" in x:
            us = True
            if 'United States' in countries:
                countries.remove('United States')
            if 'Canada' in countries:
                countries.remove('Canada')

        if len(countries) > 0:
            if us:
                return Trial.BOTH
            else:
                return Trial.NONUS
        else:
            return Trial.US if us else ''
                    

    @staticmethod
    def get_display(choices : list, ch : str) -> str:
        """
            Returns display value for a choices list given the database character
            value. It is similar to the get_FIELD_display but it works in a generic
            way.
        """
        for c, display in choices:
            if ch == c:
                return display
        return None


    @staticmethod
    def get_char(choices : list, display : str) -> str:
        """
            Returns corresponding choice character given the choices list and
            display value that we are willing to ge the character for.
        """
        for c, d in choices:
            if d == display:
                return c
        return None



class Subscriber(models.Model):
    name = models.CharField(max_length=500)
    email = models.EmailField()
    subscription_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name



class Newsletter(models.Model):
    title = models.CharField(max_length=200, null=True)
    content = models.TextField()
    text = models.TextField()
    last_edited = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)
    posted_on = models.DateTimeField(null=True)

    def __str__(self):
        return self.text[:100]



class UpdatesLog(models.Model):
    update_counts = models.SmallIntegerField()
    udpate_date = models.DateField()
