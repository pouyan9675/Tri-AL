from datetime import datetime

title_style = "font-size:22px; font-family:verdana; color:#80eef2;"
header_style = "font-size:14px; font-family:verdana; color:#5eaddb;"
description_style = "font-size:12px; color:#f0f0f0; font-family:verdana;"
trial_style = "background-color : #1e1e1e; padding : 10px; margin-bottom : 4px; margin-top : 4px; margin-left : 40px; width : 80%;"

#Trial class for keeping data altogether after reading the xml
class Trial:
	def __init__(self, xml_root):
		self.URL = xml_root.find("required_header").find("url").text #Get the URL
		self.NCT_id = xml_root.find("id_info").find("nct_id").text #Get the NCT id
		self.brief_title = xml_root.find("brief_title").text #Find the title
		self.title = xml_root.find("official_title") #Find the full title
		self.phase = xml_root.find("phase").text #Get the phase
		self.brief_description = xml_root.find("brief_summary").find("textblock").text
		self.lead_sponsor = xml_root.find("sponsors").find("lead_sponsor").find("agency").text
		self.last_update = datetime.strptime(xml_root.find("last_update_submitted").text, '%B %d, %Y') #Get the last update as a datetime
		self.posted = datetime.strptime(xml_root.find("study_first_posted").text, '%B %d, %Y')
		try: #If the trial has a detailed description, read it
			self.description = xml_root.find("detailed_description").find("textblock").text
		except:
			self.description = ""
		
		#Find all interventions
		self.drugs = []
		for intervention in xml_root.findall("intervention"):
			self.drugs.append(intervention.find("intervention_name").text)
			
	#Function to format an entry into a single string for html
	def format(self):
		ret_string = "<div style=\"{3}\"><a style=\"{2}\" href = {0}>{1}</a></br>".format(\
		self.URL, self.brief_title, title_style, trial_style)
		
		ret_string += "<h2 style=\"{4}\">{0}</h2><h2 style=\"{4}\">Study Posted: {3}</h2><h2 style=\"{4}\">Last Update: {5}</h2><h2 style=\"{4}\">{1}</h2><h2 style=\"{4}\">Sponsored by {2}</h2><h2 style=\"{4}\">Intervention(s): ".format(\
			self.NCT_id, self.phase, self.lead_sponsor, self.posted.strftime("%m/%d/%Y"), header_style, self.last_update.strftime("%m/%d/%Y"))
			
		#Add all of the interventions
		for i in range(0, len(self.drugs)):
			ret_string += self.drugs[i]
			if i < len(self.drugs) - 1:
				ret_string += ", "
				
		#Last, add in the description
		ret_string += "</h2><p style=\"{1}\">{0}</p></div></br>".format(self.brief_description, description_style)
		
		return ret_string