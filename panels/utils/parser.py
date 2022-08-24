import bs4
from bs4 import BeautifulSoup
from lxml import etree as etree_lxml


ARRAY_FIELDS = [
    "PrimaryOutcomeMeasure", 
    "PrimaryOutcomeTimeFrame", 
    "PrimaryOutcomeDescription",
    "SecondaryOutcomeMeasure",
    "SecondaryOutcomeTimeFrame",
    "SecondaryOutcomeDescription",
    "OtherOutcomeMeasure",
    "OtherOutcomeTimeFrame",
    "OtherOutcomeDescription",
    "ArmGroupDescription",
    "ArmGroupInterventionName",
    "ArmGroupLabel",
    "ArmGroupType",
    "Condition",
    "LocationCountry",
]


class FullStudyParser:
    """
        A class to parse FullStudy API XML content from the Clinicaltrials.gov
        API and apply required actions on it.
    """
    def __init__(self, xml):
        self.xml = xml
        self.tree = etree_lxml.fromstring(xml)
        
        self.data = self._parse()
        self.data['LocationsString'] = self.get_formatted_locations()


    def _get_text(self, xpath: str) -> str:
        """
            Returns the text content of a tag if exisits and returns 
            None if the tag not exists in the XML
        """
        node = self.tree.find(xpath)
        if node:
            return node.text
        else:
            return None


    def _parse(self):
        """
            Parses the XML data into a dictionary

            - Return
            ============================
            + dict : A dictionary of parsed data
        """
        data = {}

        data['NCTID'] = self.tree.findtext('.//Field[@Name="NCTId"]')
        data['Phase'] = '|'.join([p.text for p in self.tree.findall('.//Field[@Name="Phase"]')])
        data['Status'] = self.tree.findtext('.//Field[@Name="OverallStatus"]')


        data['StudyDesign'] = {}
        data['StudyDesign']['Allocation'] = self.tree.findtext('.//Field[@Name="DesignAllocation"]')
        data['StudyDesign']['PrimaryPurpose'] = self.tree.findtext('.//Field[@Name="DesignPrimaryPurpose"]')

        data['Agents'] = []
        for intervention in self.tree.findall('.//List[@Name="InterventionList"]/Struct[@Name="Intervention"]'):
            data['Agents'].append({
                'Name' : intervention.findtext('.//Field[@Name="InterventionName"]'),
                'Type' : intervention.findtext('.//Field[@Name="InterventionType"]'),
                'Description' : intervention.findtext('.//Field[@Name="InterventionDescription"]'),
            })

        data['Conditions'] = [c.text for c in self.tree.findall('.//List[@Name="ConditionList"]/Field[@Name="Condition"]')]
        data['Protocol'] = self.tree.findtext('.//Field[@Name="OrgStudyId"]')
        data['Title'] = self.tree.findtext('.//Field[@Name="OfficialTitle"]') or self.tree.findtext('.//Field[@Name="BriefTitle"]')
        
        data['Date'] = {
            'FirstPosted' : {},
            'Start' : {},
            'LastUpdate' : {},
            'PrimaryCompletion' : {},
            'Completion' : {},
        }
        data['Date']['FirstPosted'] = self.tree.findtext('.//Field[@Name="StudyFirstPostDate"]')
        data['Date']['Start'] = self.tree.findtext('.//Field[@Name="StartDate"]')
        data['Date']['LastUpdate'] = self.tree.findtext('.//Field[@Name="LastUpdatePostDate"]')
        data['Date']['PrimaryCompletion'] = self.tree.findtext('.//Field[@Name="PrimaryCompletionDate"]')
        data['Date']['Completion'] = self.tree.findtext('.//Field[@Name="CompletionDate"]')
        data['Summary'] = {
            'Brief' : {},
            'Detailed' : {},
        }
        data['Summary']['Brief'] = self.tree.findtext('.//Field[@Name="BriefSummary"]'),
        data['Summary']['Detailed'] = self.tree.findtext('.//Field[@Name="DetailedDescription"]'),

        data['Outcome'] = {
            'Primary' : [],
            'Secondary' : [],
            'Other' : [],
        }
        for primary in self.tree.findall('.//List[@Name="PrimaryOutcomeList"]/Struct[@Name="PrimaryOutcome"]'):
            data['Outcome']['Primary'].append({
                'Measure' : primary.findtext('.//Field[@Name="PrimaryOutcomeMeasure"]'),
                'TimeFrame' : primary.findtext('.//Field[@Name="PrimaryOutcomeTimeFrame"]'),
                'Description' : primary.findtext('.//Field[@Name="PrimaryOutcomeDescription"]'),
            })
        
        for secondary in self.tree.findall('.//List[@Name="SecondaryOutcomeList"]/Struct[@Name="SecondaryOutcome"]'):
            data['Outcome']['Secondary'].append({
                'Measure' : secondary.findtext('.//Field[@Name="SecondaryOutcomeMeasure"]'),
                'TimeFrame' : secondary.findtext('.//Field[@Name="SecondaryOutcomeTimeFrame"]'),
                'Description' : secondary.findtext('.//Field[@Name="SecondaryOutcomeDescription"]'),
            })

        for other in self.tree.findall('.//List[@Name="OtherOutcomeList"]/Struct[@Name="OtherOutcome"]'):
            data['Outcome']['Other'].append({
                'Measure' : other.findtext('.//Field[@Name="OtherOutcomeMeasure"]'),
                'TimeFrame' : other.findtext('.//Field[@Name="OtherOutcomeTimeFrame"]'),
                'Description' : other.findtext('.//Field[@Name="OtherOutcomeDescription"]'),
            })

        data['Criteria'] = self.tree.findtext('.//Field[@Name="EligibilityCriteria"]')
        data['Enrollment'] = self.tree.findtext('.//Field[@Name="EnrollmentCount"]')
        data['ArmsNumber'] = len(self.tree.findall('.//Struct[@Name="ArmGroup"]'))

        data['Sponsors'] = {}
        data['Sponsors']['Lead'] = {
            'Name' : self.tree.findtext('.//Field[@Name="LeadSponsorName"]'),
            'Type' : self.tree.findtext('.//Field[@Name="LeadSponsorClass"]'),
        }
        data['Sponsors']['All'] = [data['Sponsors']['Lead']]
        for colab in self.tree.findall('.//List[@Name="CollaboratorList"]/Field[@Name="Collaborator"]'):
            data['Sponsors']['All'].append({
                'Name' : colab.findtext('.//Field[@Name="CollaboratorName"]'),
                'Type' : colab.findtext('.//Field[@Name="CollaboratorClass"]'),
            })

        data['Age'] = {
            'Min' : self.tree.findtext('.//Field[@Name="MinimumAge"]'),
            'Max' : self.tree.findtext('.//Field[@Name="MaximumAge"]'),
        }

        data['Gender'] = self.tree.findtext('.//Field[@Name="Gender"]')

        data['Locations'] = []
        for loc in self.tree.findall('.//List[@Name="LocationList"]/Struct[@Name="Location"]'):
            information = {
                'Name'  : loc.findtext('.//Field[@Name="LocationFacility"]'),
                'City'  : loc.findtext('.//Field[@Name="LocationCity"]'),
                'State'  : loc.findtext('.//Field[@Name="LocationState"]'),
                'Country'  : loc.findtext('.//Field[@Name="LocationCountry"]'),
                'ZipCode'  : loc.findtext('.//Field[@Name="LocationZip"]'),
            }
            data['Locations'].append(information)

        data['Countries'] = set([f['Country'] for f in data['Locations'] if f['Country'] != None])


        return data


    def _preprocess_data(self, data):
        """
            A function to perfrom preprocess to data in parser level

            - Parameters
            ============================
            + data:  A dictionary of parsed data

            
            - Return
            ============================
            + dict : Preprocessed data
        """
        data['PrimaryOutcome'] = self._format_outcome(data["PrimaryOutcomeMeasure"], data["PrimaryOutcomeTimeFrame"], data["PrimaryOutcomeDescription"])
        data['SecondaryOutcome'] = self._format_outcome(data["SecondaryOutcomeMeasure"], data["SecondaryOutcomeTimeFrame"], data["SecondaryOutcomeDescription"])
        data['OtherOutcome'] = self._format_outcome(data["OtherOutcomeMeasure"], data["OtherOutcomeTimeFrame"], data["OtherOutcomeDescription"])

        for k, v in data.items():
            if k == 'PrimaryOutcomeTimeFrame':  # overriding process
                data[k] = set(v)


        return data


    def _format_outcome(self, measeure, time, desc):

        outcome_measure = []

        if len(measeure) == len(time) and len(time) == len(desc):
            for m, t, d in zip(measeure, time, desc):
                outcome_measure.append('- ' + m + ' [Time Frame: ' + t + ']\n\t' + d)
        elif len(measeure) == len(time):
            for m, t in zip(measeure, time):
                outcome_measure.append('- ' + m + ' [Time Frame: ' + t + ']')
        elif len(measeure) == len(desc):
            for m, d in zip(measeure, desc):
                outcome_measure.append('- ' + m + ' \n\t' + d)
        else:
            for m in measeure:
                outcome_measure.append('- ' + m)
        return '\n\n'.join(outcome_measure)

    
    def get_formatted_locations(self):
        """
            Returns the locations in a formatted string:
                Name, City, State, Country
        """
        result = []
        for l in self.data['Locations']:
            addr = ', '.join([v for k,v in l.items() if v != None and k != 'Status'])
            result.append(addr)
            
        return '\n'.join(result)



class XMLParser:
    """
        A class to the XML data downloaded from clinicaltrials.gov
        and build the corresponding Trial object to insert or update
        instances in the database
    """

    def __init__(self, xml: str):
        self.xml = xml
        self.soup = BeautifulSoup(xml, 'xml')
        self.data = self._parse()
        self.data['LocationsString'] = self.get_formatted_locations()

    
    def _tag_value(self, tag: str, node: bs4.element.Tag = None) -> str:
        """
            Retrieving value for a tag if the tag exists in the XML
        """
        if not node:
            node = self.soup

        if node.find(tag):
            return node.find(tag).text
        else:
            return None


    def _parse(self) -> dict:
        """
            The main function to yield resutls from the read XML file
        """
        data = {}

        data['NCTID'] = self.soup.nct_id.text
        data['Phase'] = self._tag_value('phase')
        data['Status'] = self.soup.overall_status.text

        data['StudyDesign'] = {}
        data['StudyDesign']['Allocation'] = self._tag_value('allocation')
        data['StudyDesign']['PrimaryPurpose'] = self._tag_value('primary_purpose')

        data['Agents'] = []
        for intervention in self.soup.find_all('intervention'):
            data['Agents'].append({
                'Name' : intervention.intervention_name.text,
                'Type' : intervention.intervention_type.text,
                'Description' : self._tag_value('description', intervention),
            })

        data['Conditions'] = [c.get_text() for c in self.soup.find_all('condition')]
        data['Protocol'] = self._tag_value('org_study_id')
        data['Title'] = self._tag_value('official_title') or self._tag_value('brief_title')
        
        data['Date'] = {
            'FirstPosted' : {},
            'Start' : {},
            'LastUpdate' : {},
            'PrimaryCompletion' : {},
            'Completion' : {},
        }
        data['Date']['FirstPosted'] = self.soup.study_first_posted.text
        data['Date']['Start'] = self._tag_value('start_date')
        data['Date']['LastUpdate'] = self.soup.last_update_submitted.text
        data['Date']['PrimaryCompletion'] = self._tag_value('primary_completion_date')
        data['Date']['Completion'] = self._tag_value('completion_date')
        data['Summary'] = {
            'Brief' : {},
            'Detailed' : {},
        }
        data['Summary']['Brief'] = self._tag_value('brief_summary'),
        data['Summary']['Detailed'] = self._tag_value('detailed_description'),

        data['Outcome'] = {
            'Primary' : [],
            'Secondary' : [],
            'Other' : [],
        }
        for primary in self.soup.find_all('primary_outcome'):
            data['Outcome']['Primary'].append({
                'Measure' : self._tag_value('measure', primary),
                'TimeFrame' : self._tag_value('time_frame', primary),
                'Description' : self._tag_value('description', primary),
            })
        
        for secondary in self.soup.find_all('secondary_outcome'):
            data['Outcome']['Secondary'].append({
                'Measure' : self._tag_value('measure', secondary),
                'TimeFrame' : self._tag_value('time_frame', secondary),
                'Description' : self._tag_value('description', secondary),
            })

        for other in self.soup.find_all('other_outcome'):
            data['Outcome']['Other'].append({
                'Measure' : self._tag_value('measure', other),
                'TimeFrame' : self._tag_value('time_frame', other),
                'Description' : self._tag_value('description', other),
            })

        data['Criteria'] = self._tag_value('textblock', self.soup.criteria) 
        data['Enrollment'] = self._tag_value('enrollment')
        data['ArmsNumber'] = self.soup.number_of_arms.text if self.soup.number_of_arms else None

        data['Sponsors'] = { 'All' : [] }
        for spon in self.soup.sponsors.children:
            if spon.name:
                data['Sponsors']['All'].append({
                    'Name' : self._tag_value('agency', spon),
                    'Type' : self._tag_value('agency_class', spon),
                })
                if spon.name == 'lead_sponsor':
                    data['Sponsors']['Lead'] = {'Name': self._tag_value('agency', spon), 'Type': self._tag_value('agency_class', spon)}

        data['Age'] = {
            'Min' : self._tag_value('minimum_age'),
            'Max' : self._tag_value('maximum_age'),
        }

        data['Gender'] = self._tag_value('gender')

        data['Locations'] = []
        for loc in self.soup.find_all('location'):
            if loc.find('facility'):
                facility = loc.facility
                information = {
                    'Name'  : self._tag_value('name', facility.address),
                    'City'  : self._tag_value('city', facility.address),
                    'State'  : self._tag_value('state', facility.address),
                    'Country'  : self._tag_value('country', facility.address),
                    'Status': self._tag_value('status', loc),
                }
                data['Locations'].append(information)

        data['Countries'] = set([f['Country'] for f in data['Locations'] if f['Country'] != None])

        return data


    def get_formatted_locations(self):
        """
            Returns the locations in a formatted string:
                Name, City, State, Country
        """
        result = []
        for l in self.data['Locations']:
            addr = ', '.join([v for k,v in l.items() if v != None and k != 'Status'])
            result.append(addr)
            
        return '\n'.join(result)