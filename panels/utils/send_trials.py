import time
from datetime import datetime
import ssl
import trial
import urllib.request, urllib.error, urllib.parse
import zipfile
import xml.etree.ElementTree as ET
import os
import sys
import smtplib as smtp
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

refresh_time = 86400 #Number of seconds before a refresh
port = 465  # For SSL
user = "ulabsunlv"
email = "ulabsunlv@gmail.com"
password = "2021SBALU!!"
query_URL = "https://clinicaltrials.gov/ct2/results/download_studies?cond=Alzheimer+Disease&term=&type=&rslt=&recrs=b&recrs=a&recrs=f&recrs=d&age_v=&gndr=&intr=&titles=&outc=&spons=&lead=&id=&cntry=&state=&city=&dist=&locn=&phase=0&phase=1&phase=2&rsub=&strd_s=1%2F1%2F2021&strd_e=&prcd_s=&prcd_e=&sfpd_s=&sfpd_e=&rfpd_s=&rfpd_e=&lupd_s=&lupd_e=&resultxml=true"
#feed_link = "https://clinicaltrials.gov/ct2/results/rss.xml?rcv_d=&lup_d=14&sel_rss=mod14&recrs=abdf&cond=Alzheimer+Disease&phase=012&strd_s=01%2F01%2F2021&count=50"
recipients = ["blacks1@unlv.nevada.edu", "jcummings@cnsinnovations.com", "garam.lee@biogen.com", "garam.lee02@gmail.com", "jorge.fonsecacacho@unlv.edu"] #List of emails to receive the notifications
#recipients = ["blacks1@unlv.nevada.edu"] #List of emails to receive the notifications (DEBUG)

#Style for each trial div node
email_style = "background-color: #2a2a2a;"

#Function to receive the data from the clinical trials site and save items
def retrieveTrials():
	#Download the zip file from the site
	response = response = urllib.request.urlopen(query_URL)
	content = response.read()
	
	#Delete the old zip file and directory
	if os.path.exists("trials.zip"):
		os.remove("trials.zip")
		
	if os.path.exists("trials"):	
		for filename in os.listdir("trials"):
			os.remove("trials/" + filename)
		os.rmdir("trials")
	
	#Save the zip file
	zip_file = open("trials.zip", "wb")
	zip_file.write(content)
	zip_file.close()
	
	#Extract it
	with zipfile.ZipFile("trials.zip", 'r') as zip_ref:
		zip_ref.extractall("trials")
		
#Reads all of the trial files and returns an array containing all of the trials as objects	
def readAllTrials():
	trials = []

	if os.path.exists("trials"):	
		for filename in os.listdir("trials"):
			tree = ET.parse("trials/" + filename)
			root = tree.getroot()
			trials.append(trial.Trial(root))
			
	return trials
	
#Finds all trials that were updated after the most recent entry
def findNewTrials(trials, most_recent_entry):
	new_trials = []
	for trial in trials:
		if (trial.posted > most_recent_entry):
			new_trials.append(trial)
			
			#DEBUG Biomarker log
			trial_description = trial.description.lower().split()
			if "biomarker" in trial_description or "biomarkers" in trial_description:
				writeToBiomarkerLog(trial.description)
		
	return new_trials
	
#Finds the most recent update time from the list of trials. Assume that the trials array is not empty
def findMostRecentEntry(trials):
	newest = trials[0].posted
	for trial in trials:
		if(trial.posted > newest):
			newest = trial.posted
	return newest


#Sends emails to all recipients in the recipient list
def sendEmails(sender_email, message):
    # Create a secure SSL context
    context = ssl.create_default_context()

    #Make the actual email object
    email_msg = MIMEMultipart('alternative')
    email_msg['subject'] = "Clincal Trial Updates"
    email_msg['From'] = sender_email
    email_msg.preamble = ""
    html = MIMEText(message, 'html')
    email_msg.attach(html)
    
    with smtp.SMTP_SSL("smtp.gmail.com", port, context=context) as server: #Connect to Gmail's SMTP server
        server.login(user, password) #Login to the server
        #server.connect("smtp.gmail.com", port)

        for recipient in recipients: #Send emails to all recipients
            email_msg['To'] = recipient
            server.sendmail(sender_email, recipient, email_msg.as_string())

        server.quit() #Log out from the server
		
def writeToLog(message):
	log = open("trials_log.txt", "a")
	log.write("[{0}] {1}\n".format(datetime.now().strftime("%m/%d/%Y %H:%M:%S"), message))
	log.close()

def writeToBiomarkerLog(message):
	log = open("biomarker_log.txt", "a")
	log.write("[{0}]\n {1}\n\n".format(datetime.now().strftime("%m/%d/%Y %H:%M:%S"), message))
	log.close()

#Ask for credentials
#email = input("Enter the email to send from:\n ")
#password = input("\nType your password and press enter:\n")

#DEBUG Send emails as test
#retrieveTrials() #Download recent trials
#trials = readAllTrials() #Read all of the trial files
#send_string = "<html><div style = {0}>".format(email_style)
#for new_trial in trials:
#	send_string += new_trial.format()
#send_string += "</div></html>"
	
#sendEmails(email, send_string)

try:
	#Create a logger
	writeToLog("Script began running")

	#Do an initial pull
	most_recent_entry = datetime.now()	

	#Do a pull every few minutes and then check for any new entries
	while True:
		time.sleep(refresh_time) #Sleep before refreshing again
		writeToLog("Checking for updates")
		
		retrieveTrials() #Download recent trials
		trials = readAllTrials() #Read all of the trial files
		new_trials = findNewTrials(trials, most_recent_entry) #Find any new trials since the last email
		
		if(len(new_trials) > 0): #If there were new trials, email them and update the most_recent_entry
			writeToLog("{0} new trials are being sent".format(len(new_trials)))
			
			send_string = "<html><div style = {0}>".format(email_style)
			for new_trial in new_trials:
				send_string += new_trial.format()
			send_string += "</div></html>"
				
			sendEmails(email, send_string)
			
			most_recent_entry = findMostRecentEntry(new_trials)
			
			#Free up memory before we go back to sleep
			del trials
			del new_trials
			del send_string
except:
	print("Error: {0}", str(sys.exc_info()[0]))
	writeToLog(str(sys.exc_info()[0]))