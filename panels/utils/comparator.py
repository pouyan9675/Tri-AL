from datetime import datetime
from panels.models import *
from panels.utils import tools

class TrialComparator:
    
    def __init__(self, updatable_fields=None):

        if updatable_fields:
            self.updatable_fields = updatable_fields
        else:
            self.updatable_fields = {
                'phase' : 'Phase',
                'status' : 'Status',
                'protocol' : 'Protocol',
                'title' : 'Title',
                'first_posted' : ('Date', 'FirstPosted'),
                'start_date' : ('Date', 'Start'),
                'primary_completion' : ('Date', 'PrimaryCompletion'),
                'end_date' : ('Date', 'Completion'),
                'last_update' : ('Date', 'LastUpdate'),
                'study_duration' : 'StudyDuration',
                # 'treatment_duration' : 'Treatment Duration',
                # 'treatment_weeks' : 'in Weeks',
                # 'treatment_days' : 'in Days',
                'enroll_number' : 'Enrollment',
                'arms_number' : 'ArmsNumber',
                'per_arm' : 'PerArm',
                'location' : 'Locations',
                'location_str' : 'LocationsString',
                'num_sites' :   'NumSites',
                'primary_outcome' : ('Outcome', 'Primary'),
                'secondary_outcome' : ('Outcome', 'Secondary'),
                'other_outcome' : ('Outcome', 'Other'),
                'eligibility_criteria' : 'Criteria',
            }
    

    def _str_list_check(self, l1, l2, sep):
        """
            Check whether two str lists are same or not given 
            lists items separator regardless of their element 
            ordering.
        """
        if l1 and isinstance(l1, str):
            l1 = set([x.strip() for x in l1.split(sep)])
        elif l1 and isinstance(l1, list):
            l1 = set(l1)
        else:
            l1 = set()

        if l2 and isinstance(l2, str):
            l2 = set([x.strip() for x in l2.split(sep)])
        elif l2 and isinstance(l2, list):
            l2 = set(l2)
        else:
            l2 = set()

        return l1 != l2


    def update_database(self, row):
        """
            Compares two trial objects as a dictionary or a Pandas 
            row to find the changes of two objects and update the
            differences.

        - Parameters
        ============================
        + new:     A single row of a dataframe

        - Return
        ============================
        + dict :   A dict (object attribute : pandas column) of fields 
                    that need to be updates
        """
        t = Trial.objects.get(nct_id=row['NCTID'])

        # TODO: updating calculations

        for attr, column in self.updatable_fields.items():
            if isinstance(column, str):
                new, old = row[column], getattr(t, attr)
            elif isinstance(column, tuple):
                new, old = row[column[0]][column[1]], getattr(t, attr)
                if column[0] == 'Date':
                    new = tools.read_date(new)

            if isinstance(new, datetime):
                if new.date() != old:
                    setattr(t, attr, new)

            elif isinstance(new, int) or isinstance(new, float):       
                if old is None:
                    old = 0

                if float(new) != float(old):
                    setattr(t, attr, new)

            elif attr == 'treatment_duration' or attr == 'location_str':
                if self._str_list_check(new, old, '\n'):
                    setattr(t, attr, new)

            # compare the rest normally
            else:
                if new != old:
                    setattr(t, attr, new)


            for s in row['Sponsors']['All']:
                try:
                    sponsor = Sponsor.objects.get(name=s['Name'])
                    if sponsor not in t.sponsor.all():
                        t.sponsor.add(sponsor)
                except Sponsor.DoesNotExist:
                    sponsor = Sponsor(name=s['Name'])
                    sponsor.save()
                    t.sponsor.add(sponsor)


        return t
