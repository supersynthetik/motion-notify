#!/usr/bin/python2
"""Updated: 5th May 2019.

Motion Notify v0.9 - uploads images and video to Google Drive and sends
 notification via email.
Detects whether someone is home by checking the local network for an IP
 address or MAC address and only sends email if nobody is home.
Allows hours to be defined when the system will be active regardless of
 network presence.

Optionally ends an email to the user at that start of an event and uploads
 images throughout the event.
At the end of an event the video is uploaded to Google Drive and a link
 is emailed to the user.
Files are optionally deleted once they are uploaded.
Options to manually delete specified number of days of the oldest file
 from drive or to autoclean oldest drive files to reduce storage fullness
 below specified threshold.

Updated to support Google OAuth2 with service account and drive quota &
file maintenance by Benjamin Millar.
Originally developed by Andrew Dean, based on the Google Drive uploader
 by Jeremy Blythe (http://jeremyblythe.blogspot.com) and pypymotion
 (https://github.com/7AC/pypymotion) by Wayne Dyck
"""

# This file is part of Motion Notify.
#
# Motion Notify is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Motion Notify is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Motion Notify.  If not, see <http://www.gnu.org/licenses/>.

import ConfigParser
import base64
import logging.handlers
import os
import smtplib
import subprocess
import sys
import time
import traceback
from datetime import date
from datetime import datetime
from datetime import timedelta
import httplib2
from apiclient import errors
from apiclient.discovery import build
from apiclient.http import MediaFileUpload
from oauth2client.file import Storage
from oauth2client.service_account import ServiceAccountCredentials

logger = logging.getLogger('MotionNotify')
hdlr = logging.handlers.RotatingFileHandler('/var/tmp/motion-notify.log',
                                            maxBytes=1048576,
                                            backupCount=3)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)

def loggerExceptHook(t, v, tb):
    logger.error(traceback.format_exception(t, v, tb))

sys.excepthook = loggerExceptHook

class MotionNotify:
    """Main class for motion-notify"""

    def __init__(self, config_file_path):
        """Initialise script & get configs."""
        logger.info('Loading config')
        # Load config
        config = ConfigParser.ConfigParser()
        config.read(config_file_path)
        logger.info('Config file read')
        # GMail account credentials
        self.username = config.get('gmail', 'user')
        self.password = config.get('gmail', 'password')
        self.from_name = config.get('gmail', 'name')
        self.sender = config.get('gmail', 'sender')

        # Recipient email address (could be same as from_addr)
        self.recipient = config.get('gmail', 'recipient')

        # Subject line for email
        self.subject = (config.get('gmail', 'subject')
                        + ' ' + time.strftime('%H:%M:%S'))

        # First line of email message
        self.message = config.get('gmail', 'message')

        # API to use
        self.service_name = config.get('drive', 'service_name')

        # API version to use
        self.service_api_version = config.get('drive', 'service_api_version')

        # Authorised scope
        self.service_scope = config.get('drive', 'service_scope')

        # Client email for service account
        self.service_account_email = config.get('drive',
                                                'service_account_email')

        # Path to private key for service account
        self.private_key_path = config.get('drive', 'private_key_path')

        # ID of Drive folder to upload files to
        self.folder_id = config.get('drive', 'folder_id')

        # Description added to uploaded files
        self.description = config.get('drive', 'description')

        # Options
        self.delete_files = config.getboolean('options', 'delete-files')
        self.send_email = config.getboolean('options', 'send-email')
        self.keep_days = config.getint('options', 'keep-days')
        self.autoclean_percent = config.getint('options', 'autoclean-percent')
        self.autoclean_increment = config.getint('options', 'autoclean-increment')
        self.google_drive_folder_link = config.get('gmail',
                                                   'google_drive_folder_link')
        self.event_started_message = config.get('gmail',
                                                'event_started_message')
        self.presenceMacs = []
        self.network = None
        self.ip_addresses = None

        try:
            self.presenceMacs = config.get('LAN', 'presence_macs').split(',')
            self.network = config.get('LAN', 'network')
        except ConfigParser.NoSectionError, ConfigParser.NoOptionError:
            pass

        try:
            self.ip_addresses = config.get('LAN', 'ip_addresses')
        except ConfigParser.NoSectionError, ConfigParser.NoOptionError:
            pass

        try:
            self.forceOnStart = config.getint('activate-system',
                                              'force_on_start')
            self.forceOnEnd = config.getint('activate-system',
                                            'force_on_end')
        except ConfigParser.NoSectionError, ConfigParser.NoOptionError:
            pass

        logger.info('All config options set')

    def _get_service(self):
        """Creates or gets stored credentails to use with service account."""
        cred_storage = (os.path.join(
            os.path.dirname(self.private_key_path),
            '{}-credentials.json'.format(self.service_name)))
        storage = Storage(cred_storage)
        credentials = storage.get()
        http = httplib2.Http()

        if credentials is None or credentials.invalid:
            """Assumes Google isn't going to change its default key"""
            private_key_password = 'notasecret'
            credentials = (ServiceAccountCredentials.from_p12_keyfile
            (self.service_account_email, self.private_key_path,
             private_key_password, scopes=self.service_scope))
            storage.put(credentials)
        else:
            credentials.refresh(http)

        http = credentials.authorize(http)
        return build(serviceName=self.service_name,
                     version=self.service_api_version,
                     http=http)

    def _send_email(self, msg, media_file_path):
        """Send an email using the GMail account."""
        senddate = datetime.strftime(datetime.now(), '%Y-%m-%d')
        marker = 'AUNIQUEMARKER'
        p1 = ('Date: %s\r\nFrom: %s <%s>\r\nTo: %s\r\nSubject: %s\r\n'
              'Content-Type: multipart/mixed; boundary=%s\r\n--%s\r\n'
              % (senddate, self.from_name, self.sender, self.recipient,
                 self.subject, marker, marker))
        p2 = ('Content-Type: text/plain\r\nContent-Transfer-Encoding:8bit\r'
              '\n\r\n%s\r\n--%s\r\n' % (msg, marker))
        # If motion is setup to capture a jpg with same name as video,
        #  add as email attachment
        vname = media_file_path.split('.')
        fname = vname[0] + '.jpg'
        if os.path.isfile(fname):
            # Read a file and encode it into base64 format
            fo = open(fname, 'rb')
            filecontent = fo.read()
            encodedcontent = base64.b64encode(filecontent)  # base64
            imgfile = os.path.basename(fname)
            p3 = ('Content-Type: image/jpeg; name=''%s''\r\nContent-Transfer-'
                  'Encoding:base64\r\nContent-Disposition: attachment; '
                  'filename=%s\r\n\r\n%s\r\n--%s--\r\n'
                  % (imgfile, imgfile, encodedcontent, marker))
            message = p1 + p2 + p3
        else:
            message = p1 + p2

        server = smtplib.SMTP('smtp.gmail.com:587')
        server.starttls()
        server.login(self.username, self.password)
        server.sendmail(self.sender, self.recipient, message)
        server.quit()

    def _upload_file(self, service, filename, description, mime_type,
                     parent_id=None):
        """Uploads file to specified service."""
        media_body = MediaFileUpload(filename, mimetype=mime_type,
                                     resumable=True)
        body = {
            'title': os.path.basename(filename),
            'mimeType': mime_type,
            'description': description,
        }
        if parent_id:
            body['parents'] = [{'id': parent_id}, ]
        return service.files().insert(body=body,
                                      media_body=media_body).execute()

    def _system_active(self):
        """System active if forced active or specified devices present."""
        now = datetime.now()
        system_active = True
        # Ignore presence if force_on specified
        if ((self.forceOnStart >= 0) and (self.forceOnEnd <= 23) and
                (now.hour >= self.forceOnStart) and (now.hour <= self.forceOnEnd)):
            logger.info('System is forced active at the current time - '
                        'ignoring network presence')
            return True
        else:
            if self.ip_addresses:
                system_active = self._system_active_ip_based()
            else:
                if self.network and self.presenceMacs:
                    system_active = self._system_active_arp_based()
            logger.info('Based on network presence should the email be '
                        'sent %s', system_active)
        return system_active

    def _email_required(self, notify):
        logger.info('Checking if email required')
        if not self.send_email or not notify:
            logger.info('Either email is disabled globally or is disabled for'
                        ' this task via command line parameters')
            return False
        logger.info('Email required for this task')
        return True

    def _system_active_arp_based(self):
        """Checks for configured MAC addresses."""
        if not self.network or not self.presenceMacs:
            return None
        logger.info('Checking for presence via MAC address')
        result = (subprocess.Popen(
            ['sudo', 'arp-scan', self.network], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT).stdout.readlines())
        logger.info('result %s', result)
        for addr in result:
            for i in self.presenceMacs:
                if i.lower() in addr.lower():
                    logger.info('ARP entry found - someone is home')
                    return False
        logger.info('No ARP entry found - nobody is home - system is active')
        return True

    def _system_active_ip_based(self):
        """Checks for prescence of configured IPs."""
        if not self.ip_addresses:
            logger.info('No IP addresses configured - skipping IP check')
            return True
        logger.info('Checking for presence via IP address')
        addresses = self.ip_addresses.split(',')
        for address in addresses:
            test_string = 'bytes from'
            results = (subprocess.Popen(
                ['ping', '-c1', address], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT).stdout.readlines())
            logger.info('Nmap result %s', results)
            for result in results:
                if test_string in result:
                    logger.info('IP detected - someone is home')
                    return False
        logger.info('IP inactive - nobody is home - system is active')
        return True

    def upload_media(self, media_file_path, notify):
        """Upload media file to the specified folder. Then optionally send
        an email, optionally delete the local file, and/or purge oldest
        files from drive to reach target storage fullness threshold."""
        if self._system_active():
            if media_file_path.endswith('jpg'):
                logger.info('Uploading image %s ' % media_file_path)
                mime_type = 'image/jpeg'
            else:
                if media_file_path.endswith(('avi', 'flv', 'mov', 'mpg', 'swf', 'mp4')):
                    logger.info('Uploading video %s ' % media_file_path)
                    mime_type = 'video/avi'

            service = self._get_service()
            doc = self._upload_file(service=service,
                                    filename=media_file_path,
                                    description=self.description,
                                    mime_type=mime_type,
                                    parent_id=self.folder_id)

            # Config file has email enable and it is set to true
            #  on the command line
            if self._email_required(notify):
                media_link = None
                media_link = doc['alternateLink']
                msg = self.message
                if media_link:
                    msg += '\n\n' + media_link
                self._send_email(msg, media_file_path)

            if self.delete_files:
                logger.info('Deleting: %s', media_file_path)
                os.remove(media_file_path)
                # If motion is setup to capture a jpg with same name as video,
                #  add as email attachment
                vname = media_file_path.split('.')
                fname = vname[0] + '.jpg'
                if os.path.isfile(fname):
                    os.remove(fname)
                    logger.info('Deleting: %s', fname)
        if 1 <= self.autoclean_percent < 100:
            logger.info('Autoclean active')
            while self.get_drive_info(service) > self.autoclean_percent:
                logger.info('Drive storage above threshold, proceeding with autoclean')
                trigger = 'auto'
                self.cleanup_media(trigger)
                #Brief pause to let drive storage quota catch up
                time.sleep(5)

    def send_start_event_email(self, media_file_path, notify):
        """Send an email showing that the event has started."""
        if self._email_required(notify) and self._system_active():
            msg = self.event_started_message
            msg += '\n\n' + self.google_drive_folder_link
            self._send_email(msg, media_file_path)

    def get_drive_info(self, service):
        """Get Google drive info and write it to the log."""
        try:
            about = service.about().get().execute()
            logger.info('Current user name: %s' % about['name'])
            logger.info('Root folder ID: %s' % about['rootFolderId'])
            remain = (float(about['quotaBytesTotal'])
                      - float(about['quotaBytesUsed'])) / 1073741824
            used = float(about['quotaBytesUsed']) / 1073741824
            logger.info('Remaining quota (GiB): %.3f' % remain)
            logger.info('Used quota (GiB)     : %.3f' % used)
            percent = (float(about['quotaBytesUsed'])/float(about['quotaBytesTotal']))*100
            logger.info('Drive fullness: %.0f%%' % percent)
            if percent > 95:
                logger.warning('%.0f%% Drive storage used.  Acquire more storage or '
                               'cleanup old data' % percent)
        except errors.HttpError, error:
            logger.error('An error occurred: %s' % error)
        return percent

    def get_files_list(self, service):
        """Fetch list of all files owned by the current user."""
        result = []
        page_token = None
        while True:
            try:
                param = {}
                if page_token:
                    param['pageToken'] = page_token
                files = service.files().list(**param).execute()

                result.extend(files['items'])
                page_token = files.get('nextPageToken')
                if not page_token:
                    break
            except errors.HttpError, error:
                logger.error('An error occurred: %s' % error)
                break
        return result

    def filter_files_list(self, list, date):
        """Filter list of all files to get those outside the retention window."""
        filter = []
        for item in list:
            if datetime.strptime(item['createdDate'], '%Y-%m-%dT%H:%M:%S.%fZ') < date:
                filter.append(item)
        return filter

    def cleanup_media(self, trigger):
        """Deletes files previously uploaded by the service account that are outside
        the retention window specified in the config file for a manual cleanup, a
	dry-run of this, or an automated cleanup that will delete the oldest data
	in specified increments until the target storage fullness threshold is reached"""
        service = self._get_service()
        percent = self.get_drive_info(service)
        batch = service.new_batch_http_request(callback=delete_files)
        result = self.get_files_list(service)
        if len(result) == 0:
            logger.info('No files in Google drive.')
            exit()
        oldest = datetime.strptime(min(item['createdDate'] for item in result), '%Y-%m-%dT%H:%M:%S.%fZ')
        logger.info('Oldest file: %s' % str(oldest))
        if (trigger == 'manual') or (trigger == 'dryrun'):
            keep = datetime.today() - timedelta(days=self.keep_days)
        if trigger == 'auto':
            keep = oldest + timedelta(hours=self.autoclean_increment)
        filter = self.filter_files_list(result, keep)
        logger.info('Targetting files older than: %s' % str(keep))
        if trigger == 'dryrun':
            logger.info('Drive cleanup in dry-run mode.')
        count = 0
        for item in filter:
            if (trigger == 'manual') or (trigger == 'auto'):
                batch.add(service.files().delete(fileId=item['id']))
                count += 1
            #Max 100 ops per batch request
            if count > 99:
                batch.execute()
                count = 0
        #Final batch execution to complete the cleanup
        batch.execute()
        logger.info('Total Files: %i' % len(result))
        logger.info('Eligible for removal: %i' % len(filter))

def delete_files(request_id, response, exception):
    if exception is not None:
        # Do something with the exception
        pass
    else:
        # Do something with the response
        pass

if __name__ == '__main__':
    logger.info('Motion Notify script started')
    try:
        if len(sys.argv) < 3:
            exit('Usage: motion-notify.py {configfile-path} {mediafile-path}'
                 ' {send-email (optional: "1" if email required, "0" if not)}\n'
                 'Alt usage: motion-notify.py {configfile-path}'
                 ' {cleanup-flag ("cleanup" to trigger drive cleanup to'
		 ' specified retention or "cleanup_dryrun" to trigger dry-run'
		 ' of drive cleanup)}'
                 )
        cfg_path = sys.argv[1]
        vid_path = sys.argv[2]
        try:
            if sys.argv[3] == '1':
                notify = True
            else:
                notify = False
        except IndexError:
            notify = False
        if vid_path == 'cleanup_dryrun':
            trigger = 'dryrun'
            MotionNotify(cfg_path).cleanup_media(trigger)
            exit('Drive cleanup dryrun triggered')
        if vid_path == 'cleanup':
            trigger = 'manual'
            MotionNotify(cfg_path).cleanup_media(trigger)
            exit('Drive cleanup triggered')
        if not os.path.exists(cfg_path):
            exit('Config file does not exist [%s]' % cfg_path)
        if vid_path == 'None':
            MotionNotify(cfg_path).send_start_event_email(vid_path, notify)
            exit('Start event triggered')
        if not os.path.exists(vid_path):
            exit('Video file does not exist [%s]' % vid_path)

        MotionNotify(cfg_path).upload_media(vid_path, notify)
    except Exception as e:
        exit('Error: [%s]' % e)
