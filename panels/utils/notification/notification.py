import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.shortcuts import render
from visual import settings
from panels.models import *


class Email:
    """
        Base class for sending any email in from the system
        using the configuration defined the settings file
        of the project.
    """
    def __init__(self, username=settings.EMAIL_USERNAME, 
                password=settings.EMAIL_APP_PASSWORD, 
                smtphost=settings.EMAIL_SMPT_HOST, 
                port=settings.EMAIL_PORT):

        self.username = username
        self.password = password
        self.smtphost = smtphost
        self.port = port


    def __enter__(self):
        self.server = smtplib.SMTP(self.smtphost, port=self.port)
        self.server.starttls()
        try: 
            self.server.login(self.username, self.password)
        except Exception as e:
            raise Exception(f"Failed to login {e=}, {type(e)=}")


    def __exit__(self, exc_type, exc_value, exc_tb):
        self.server.quit()


    def send_html(self, to, content, title=None):
        """
            Sends an email with HTML content as body

            Parameters
            ================
            - to:       A list of recipients of the email
            - content:  Content of the email in HTML format
            - title:    An optional title for the email
        """
        msg = MIMEMultipart()
        msg.attach(MIMEText(content, 'html'))
        msg['From'] = self.username
        
        if isinstance(to, list):
            msg['To'] = ', '.join(to)
        elif isinstance(to, str):
            msg['To'] = to
        else:
            raise TypeError('Recipents must to be either a list or str')

        if title:
            msg['Subject'] = title

        self.server.send_message(msg)


class NewTrialNotification(Email):
    """
        Notifiying admin and other users about updating news trials
        in the database along with some useful information about the
        updated trials. 
    """
    def __init__(self, template='notification/update_trial.html'):
        super().__init__()
        self.template = template

    def send(self, recipients, context):
        super().send_html(to=recipients, 
                content=render(None, self.template, context).content.decode('utf-8'),
                title='Clinical Trials Update - ' + context['update_date']
        )


class NewsletterNotification(Email):
    """
        Sends email to all subscribers about a recent news that is
        published.
    """
    def __init__(self, template='notification/newsletter.html'):
        super().__init__()
        self.template = template

    def broadcast(self, context):
        subscribers = Subscriber.objects.values_list('name', 'email')

        for name, email in subscribers:
            context['name'] = name
            super().send_html(to=email, 
                    content=render(None, self.template, context).content.decode('utf-8'),
                    title="Alzheimer's Clinical Trial InnOvation Newsletter"
            )

    

def notify_update(new_pk, updated_pk, now):
    if len(new_pk) == 0:
        return

    trials = []
    new = Trial.objects.filter(pk__in=new_pk)
    for t in new:
        agents = t.agent.all()
        
        agents_type = set([a.type for a in agents])
        if Agent.DRUG not in agents_type and Agent.BIOLOGICAL not in agents_type:
            continue

        trials.append({
            'nct_id' : t.nct_id,
            'pk'     : t.pk,
            'agent'  : [{'name':a.name,'type':a.get_type_display()} for a in agents if a.name.lower() != 'placebo'],
        })

    ctx = {
        'trials_num'  : len(new_pk)+len(updated_pk),
        'update_date' : now.strftime('%B %-d, %Y'),
        'update_time' : now.strftime('%I:%M %p'),
        'trials'      : trials,
    }
    
    notif = NewTrialNotification()
    with notif:
        notif.send(settings.UPDATE_RECIPIENTS, ctx)
    print('Notification sent successfully...')