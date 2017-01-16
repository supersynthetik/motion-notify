# motion-notify

This Motion Notify is a simple notification system for Linux Motion providing upload to Google Drive and email notificaiton of detected events.
This carries out the following:

- Records video when motion event starts
- Uploads video to Google Drive when the event ends
- Sends an email when the event ends with a link to the video
- Detects whether you're at home by looking for certain IP addresses on your local network and doesn't send alerts if you're home
- Allows you to specify hours when you want to receive alerts even if you're at home
- Optionally sends email notification as soon as motion is detected
- Optionally embed image preview in email with video link or upload image preview to Drive

Only receive alerts when you're not home.  
The script detects whether you're at home by checking the network for the presence of certain devices by IP address or MAC address.  
It's highly recommended to use IP rather than MAC. If you choose to use MAC you will need to run the script (and Motion) as root as it uses ARP - this isn't recommended. IP detection uses ping so will run as a regular user.  
Specify either a comma separated list of IP addresses or a comma separated list of MAC addresses. IP addresses take priority so if you specify those, the MAC addresses will be ignored.  
Note that mobile phones often don't retain a constant connection to the wireless network even though they show that they are connected. They tend to sleep and then just reconnect occassionally to reduce battery life.  
This means that you might get a lot of false alarms if you just use a mobile phone IP address.  
Adding lots of devices that are only active when you're at home will reduce false alarms - try things like your Smart TV, desktop PC etc as well as any mobile phones.  
It's highly recommended to configure your devices to use static IP's to prevent the IP addresses from changing.  

### Google Account Setup

For the email settings it is recommeneded that you use 2-factor authentication for the account and generate an app-specific password for the script to use.  
See: https://support.google.com/accounts/answer/185833?hl=en  

Login to Google Drive and create a folder where images and video will be upload to.  
Alternately, create another Google account just for sending alerts and create the folder in the Google Drive for the new account you created and then share that folder with your main Google account.  
This has to be a folder as you cannot share the Drive root with another account.  

Make a note of the folder ID in the URL: https://drive.google.com/drive/folders/$FOLDERID e.g. https://drive.google.com/drive/folders/xxxxxxxxxxxxxxxxxxxxxxxxx where $FOLDERID = xxxxxxxxxxxxxxxxxxxxxxxxx  
Add your folder_id to the motion-notify.cfg file under $FOLDERID  

### Google Service Account Setup
1. Sign in to your Google account
2. Go to: https://console.developers.google.com/
3. Create new project
4. From the menu, go to "API manager"
5. Click "Library", search for "Drive API" and enable it
6. ClicK "Credentials" then "Create Credentials" and select "Service Account Key"
7. Create new service account and give it a name and role "Service Account Actor"
8. Select "P12" format and Create (Password for accessing it will be shown in pop-up, you may never need it, but it's better to put it to some secret place)
9. Download that key and keep it private on your system
10. Add location of key to motion-notify.cfg under $/PRIVATE/KEY/PATH.p12 e.g. /etc/motion-notify/xxxx.p12
11. From the menu, go to "IAM & Auth" then "Service Accounts"
12. After that you will see "Service Account ID" for your account e.g. XXXX@xxxx.gserviceaccount.com
13. Add the email address to motion-notify.cfg file under $SERVICEACCOUNTEMAIL
14. Go to Google Drive to the folder created earlier and open "Sharing settings" for it
15. Add your $SERVICEACCOUNTEMAIL to the list of allowed users and allow it to edit the contents of that folder

### Installation
There's no automated installation yet so this is the current process

#### Install Python Libraries
`sudo apt-get update`  
`sudo apt-get install python-pip python-openssl`  
`sudo pip install google-api-python-client`  

#### Create directory for files
`sudo mkdir /etc/motion-notify`

Copy motion-notify.cfg, motion-notify.py and create-motion-conf-entries.txt to the directory you created

#### Create the log file and set the permissions
`sudo touch /var/tmp/motion-notify.log`  
`sudo chown motion.motion /var/tmp/motion-notify.log`  
`sudo chmod 664 /var/tmp/motion-notify.log`  

#### Setup output directory
`sudo mkdir $/OUTPUT/DIR`  
`sudo chown motion.motion $/OUTPUT/DIR`
`sudo echo "target_dir $/OUTPUT/DIR" >> /etc/motion/motion.conf`

#### Edit the config file and enter the following:
- Google account details into the GMail section of the config file
- Email address to send alerts to
- The URL of the folder you created in your Google account (just copy and paste it from the browser). This will be sent in the alert emails so that you can click through to the folder
- The ID of the folder you created
- The path to the private key on the system
- The service account email
- The hours that you always want to recieve email alerts even when you're home
- Either enter IP addresses or MAC addresses (avoid using MAC addresses) which will be active when you're at home

#### Change the permissions
`sudo chown motion.motion /etc/motion-notify/motion-notify.py`  
`sudo chown motion.motion /etc/motion-notify/motion-notify.cfg`  
`sudo chown motion.motion $/PRIVATE/KEY/PATH.p12`  
`sudo chmod 744 /etc/motion-notify/motion-notify.py`  
`sudo chmod 600 /etc/motion-notify/motion-notify.cfg`  
`sudo chown 600 motion.motion $/PRIVATE/KEY/PATH.p12`  

N.b.  If you manually run this script for testing it may create the drive credentials with permissions imcompatible with running as a service which will need to be changed
`sudo chown motion.motion /etc/motion-notify/drive-credentials.json`  

#### Create the entry in the Motion conf file to trigger the motion-notify script when there is an alert
`sudo cat /etc/motion-notify/create-motion-conf-entries.txt >> /etc/motion/motion.conf`  
`rm /etc/motion-notify/create-motion-conf-entries.txt`  

If you want to reveive an email notification at the start of the event uncomment the `#on_event_start` line at the end of the motion.conf file.  
If you want the image preview uploaded to drive rather than embedded in the email uncomment the `#on_picture_save` line at the end of the motion.conf file.  
If you want the image preview attached to the email with the video the `picture_filename ` in the motion.conf file should be changed to `picture_filename preview` and `output_pictures on` line set to `output_pictures best`
