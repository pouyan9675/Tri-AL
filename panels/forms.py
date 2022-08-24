from django import forms
from panels.widgets import *
from django.contrib.admin.widgets import AutocompleteSelectMultiple
from panels.models import Trial, Agent
from django.utils.safestring import mark_safe
import ast
import re


class TrialForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(TrialForm, self).__init__(*args, **kwargs)

        if not self.instance.nct_id:
            self.fields['nct_id'] = forms.CharField(max_length=10)
            for field in self.fields.keys():
                if field != 'nct_id':
                    self.fields[field].widget = forms.HiddenInput()
        else:
            self.fields['nct_id'] = forms.CharField(widget=TextView(), required=False, label='NCT ID')
            self.fields['title'] = forms.CharField(widget=TextView(), required=False, label='Trial Title')
            self.fields['protocol'] = forms.CharField(widget=TextView(), required=False, label='Protocol')
            self.fields['first_start_date'] = forms.CharField(widget=TextView(), required=False, label='Start Date at First Registration')
            self.fields['first_end_date'] = forms.CharField(widget=TextView(), required=False, label='End Date at First Registration')
            self.fields['first_primary_completion'] = forms.CharField(widget=TextView(), required=False, label='Primary Completion Date at First Registration')


            if self.instance.mmse_sent and len(self.instance.mmse_sent) < 400:
                self.fields['mmse'].help_text = "Extracted Sentence: " + self.instance.mmse_sent
            
            if self.instance.amyloid_sent and len(self.instance.amyloid_sent) < 400:
                self.fields['amyloid'].help_text = "Extracted Sentence: " + self.instance.amyloid_sent

            try:
                if self.instance.amyloid:
                    self.initial['amyloid'] = ast.literal_eval(self.instance.amyloid)

                AMYLOID_CHOICES = [
                        ('PET', 'PET'),
                        ('CSF', 'CSF'),]
                self.fields['amyloid'] = forms.MultipleChoiceField(
                            required=False,
                            widget=forms.CheckboxSelectMultiple,
                            choices=AMYLOID_CHOICES,
                        )
            except:         # support for older version of string repsentation
                pass
            
            if self.instance.primary_outcome:
                self.fields['primary_outcome'] = forms.CharField(widget=ItemView(attrs={
                    'list_items': self.preprocess_outcome(self.instance.primary_outcome)}), 
                                required=False,
                                label='Primary Outcome')
            else:
                self.fields['primary_outcome'].widget = forms.HiddenInput()

            if self.instance.secondary_outcome:
                self.fields['secondary_outcome'] = forms.CharField(widget=ItemView(attrs={
                    'list_items': self.preprocess_outcome(self.instance.secondary_outcome)}), 
                                required=False,
                                label='Secondary Outcome')
            else:
                self.fields['secondary_outcome'].widget = forms.HiddenInput()

            if self.instance.other_outcome:
                self.fields['other_outcome'] = forms.CharField(widget=ItemView(attrs={
                    'list_items': self.preprocess_outcome(self.instance.other_outcome)}), 
                                required=False,
                                label='Other Outcome')
            else:
                self.fields['other_outcome'].widget = forms.HiddenInput()


            self.fields['eligibility_criteria'] = forms.CharField(widget=ProcessedView(attrs={
                    'processed_text': self.preprocess_lines(self.instance.eligibility_criteria)}), 
                                required=False,
                                label='Eligibility Criteria')


            if self.instance.location_str:
                self.fields['location_str'] = forms.CharField(widget=ItemView(attrs={
                    'list_items': self.preprocess_items(self.instance.location_str)}), 
                                required=False,
                                label='Locations')
            else:
                self.fields['location_str'].widget = forms.HiddenInput()

            bootstrap_select_class = 'form-select form-select-sm py-0 w-auto'
            self.fields['status'].widget.attrs['class'] = bootstrap_select_class
            self.fields['phase'].widget.attrs['class'] = bootstrap_select_class
            self.fields['moa_class'].widget.attrs['class'] = bootstrap_select_class
            self.fields['location'].widget.attrs['class'] = bootstrap_select_class
            self.fields['main_agent_type'].widget.attrs['class'] = bootstrap_select_class


    def preprocess_outcome(self, text):
        if not text:
            text  = ''
        text = self.bold_words(text)
        return text.replace('\n\n', '\n')       \
                    .replace('\n\t', '<br>')    \
                    .replace('[', '<b>[')       \
                    .replace(']', ']</b>')      \
                    .split('- ')


    def preprocess_items(self, text):
        if not text:
            text  = ''
        items = text.split('\n')
        items = [i[2:] for i in items]
        return items


    def preprocess_lines(self, text):
        if not text:
            text  = ''
        text = text.replace('/', '').replace('\\', '')
        text = self.bold_words(text)
        return mark_safe(text.replace('\n', '<br>'))


    def bold_words(self, text, words=None):
        if not words:
            words=["CSF", 
                " PET ",
                "Amyloid",
                "Tau",
                "MMSE",
                "Mini-Mental State Exam",
                "CSF Amyloid",
                "CSF tau",
                " FDG ",
                "FDG-PET",
                "fluorodeoxyglucose",
                "qEEG",
                "vMRI",
                "apolipoprotein",
                "ApoE",
                "Volumetric Magnetic Resonance Imaging",
                "Magnetic Resonance Imaging",
                " MRI ",
                "Plasma Amyloid",
                "Plasma Tau",
                "Amyloid PET",
                "Tau PET",
                "Mild",
                "Moderate",
                "Severe",
                "Healthy",
                "Volunteers",
                "Preclinical",
                "MCI",
                "AD Dementia",
                "stem cell",
                ]
        
        for w in words:
            regex = re.compile(re.escape(w), re.IGNORECASE)
            text = regex.sub(' <b style="color:#F44;background-color:rgba(255, 220, 220, 0.45);padding:0.15em;">' + w.strip() + '</b> ', text)

        return mark_safe(text)



class AdvancedSearchForm(forms.ModelForm):
    
    def __init__(self, *args, **kwargs):
        super(AdvancedSearchForm, self).__init__(*args, **kwargs)


    class Meta:
        model = Trial
        exclude = ()
    