import flask
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify # For AJAX transactions
import uuid

# MongoDB Python module
from pymongo import MongoClient

import json
import logging

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

# Module to handle busy/free time scheduling
from agenda import *

#ObjectId for mongo records
from bson.objectid import ObjectId

# Favicon rendering
import os

###
# Globals
###
import CONFIG
app = flask.Flask(__name__)

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_LICENSE_KEY  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'

try: 
    dbclient = MongoClient(CONFIG.MONGO_URL)
    db = dbclient.meetings
    proposal_collection = db.proposals
    busy_collection = db.busy_times
except:
    print("Failure opening database.  Is Mongo running? Correct password?")
    sys.exit(1)

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/index")
def index():
  app.logger.debug("Entering index")
  
  init_proposals()  
  return render_template('index.html')
	
@app.route("/propose_meeting")
def propose_meeting():
	app.logger.debug("Entering propose_meeting")
	return render_template('propose_meeting.html')
	
@app.route("/proposal_created/<meeting_id>")
def proposal_created(meeting_id):
	app.logger.debug("Entering proposal_created")
	flask.session['meeting_id'] = meeting_id
	return render_template("proposal_created.html")

@app.route("/respond/<meeting_id>")
def respond(meeting_id):
	app.logger.debug("Entering respond")	
	
	init_meeting_variables(meeting_id)	
	return render_template('respond.html')
	
@app.route("/view_meeting/<meeting_id>")
def view_meeting(meeting_id):
	app.logger.debug("Entering view_meeting")
	
	init_meeting_variables(meeting_id)	
	return render_template('view_meeting.html')	
	
@app.route("/respond_gcal")
def respond_gcal():
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    app.logger.debug("Returned from get_gcal_service")
    flask.session['calendars'] = list_calendars(gcal_service)
    return render_template('respond_gcal.html')
    
@app.route("/respond_manual")
def respond_manual():
	app.logger.debug("Entering respond_manual")
	return render_template("respond_manual.html")

@app.route("/thanks")
def thanks():
	app.logger.debug("Entering thanks")
	flask.session.clear()
	return render_template("thanks.html")


#############################
#
#  AJAX request handlers
#
#############################
@app.route("/_submit_busy_times")
def submit_busy_times():
	'''
	Submit the busy times currently in the flask session object
	'''
	app.logger.debug("Entering submit_busy_times, AJAX handler")
	
	id = ObjectId(flask.session['current_meeting']['_id'])
	for cal in flask.session['busy_times']:
		for busy_times in cal.values():
			for busy_time in busy_times:
			    record = {
			    	"type": "busy_time",
			    	"proposal_ID": id,
			    	"start": busy_time[0],
			    	"end": busy_time[1],
			    	"name": flask.session['user_name']
			    }
			    busy_collection.insert_one(record)
			    
	return jsonify(result={})
	

@app.route("/_delete_meetings")
def delete_meetings():
	'''
	Delete a proposal from the DB, as well as associated busy times
	'''
	app.logger.debug("Entering delete_meetings, AJAX handler")
	meeting_ids = request.args.get("meeting_ids", type=str)
	
	meeting_ids = meeting_ids.split(";")
	for id in meeting_ids:
		if id == "":
			continue
		id = ObjectId(id)		
		proposal_collection.delete_one( {"_id": id} )
		busy_collection.delete_many( {"proposal_ID": id} )
	
	return jsonify(result={})

@app.route("/_setbusytimes")
def find_busy():
	'''
	Receive AJAX request to find the busy times 
	'''
	ids = request.args.get("calendar_ids", type=str)
	user_name = request.args.get("name", type=str)
	
	flask.session['user_name'] = user_name
	
	credentials = valid_credentials()
	gcal_service = get_gcal_service(credentials)
	
	busy_times, free_times = get_freebusy_times(gcal_service, ids)	
	flask.session['busy_times'] = busy_times	
	flask.session['free_times'] = free_times
	
	return jsonify(result={})
	
@app.route("/_ignore_busy_times")
def ignore_busy_times():
	'''
	Ignore busy times created from Google Calendar service
	'''
	app.logger.debug("Entering ignore_busy_times, AJAX handler")
	ignore_times = request.args.get("busy_times", type=str)
	
	ignore_times = [ time.split("&") for time in ignore_times.split(";") ]
	ignore_times.remove([""])
	
	for ignore_cal, start, end in ignore_times:
		for cal in flask.session['busy_times']:
			for cal_name in cal:
				if cal_name != ignore_cal:
					continue		
				for time in cal[cal_name]:
					if time[0] == start and time[1] == end:
						cal[cal_name].remove([start,end])
						break
	
	return jsonify(result={})
	
	
def get_freebusy_times(gcal_service, calendar_ids):
	'''
	Sends requests to the Google Calendar API to determine the busy times for 
	the given calendars (based on the indices). Uses those busy times to determine
	the free times of a given time duration.
	
	Args:
		gcal_service: 		Google Calendar Service Object, the service to 
							send freebusy requests to
		calendar_indices: 	String, the indices of the calendars selected
	Returns:
		busy_times, free_times: 	A tuple consisting of the busy times and 
								free times of the given calendars. Both are
								lists of the form
								[ 
								  {"cal1" : [
												[time_start,time_end],
											 	[...]
											]
								   }, 
								  {"cal2" : ...} 
								]
	'''
	busy_times = []
	free_times = []
	
	calendar_ids = calendar_ids.split(";")
	
	start_date, end_date = flask.session['daterange'].split(" - ")
	time_range_start = arrow.get(start_date + flask.session['begin_time'], "MM/DD/YYYYHH:mm:ssZZ")
	time_range_end = arrow.get(start_date + flask.session['end_time'], "MM/DD/YYYYHH:mm:ssZZ")
	end_date = arrow.get(end_date, "MM/DD/YYYY")

	app.logger.debug("Sending freebusy requests to Google Cal")
	for id in calendar_ids:
		if id == "":
			continue
			
		# Not preferred
		for cal in flask.session['calendars']:
			if cal['id'] == id:
				calendar = cal
				break
		#calendar = flask.session['calendars'][int(index)]
		calendar_name = calendar['summary']
		
		busy = {calendar_name : []}
		free = {calendar_name : []}
		timeMin = time_range_start.isoformat()
		timeMax = time_range_end.isoformat()
		
		for day in arrow.Arrow.span_range('day', time_range_start, end_date):		
			query = {
				"timeMin": timeMin,
				"timeMax": timeMax,
				"items": [
					{
						"id": calendar['id']
					}
				]
			}
			
			gcal_request = gcal_service.freebusy().query(body=query)	
			result = gcal_request.execute()
			
			for busy_time in result['calendars'][calendar['id']]['busy']:
			    start = arrow.get(busy_time['start']).to('local')
			    end = arrow.get(busy_time['end']).to('local')
			    conflict = [start.isoformat(), end.isoformat()]
			    busy[calendar_name].append(conflict)
			# Using the busy times, determine the free times
			free_time = determine_free_times(busy[calendar_name], timeMin, timeMax)
			free[calendar_name].extend(free_time)
			
			timeMin = next_day(timeMin)
			timeMax = next_day(timeMax)
		
		free_times.append(free)
		busy_times.append(busy)		
		
	return busy_times, free_times
	
def determine_free_times(busy_times, free_start, free_end):
	''' Given a list of busy times, and a free block (a beginning and ending free time),
	determines the free times. In other words, finds the complement of the busy_times.
	
	Args:
		busy_times: 		A list of busy times in the form [
															 	[start, end],
															 	[...]
															 ]
		free_start: 		A string representing the isoformat of the start time of the
							free block.
		free_end:			A string representing the isoformat of the end time of the
							free block.
							
	Returns:
		free_times:			A list of free times the form [
																[start, end],
																[...]
														  ]
	'''
	# app.logger.debug("Determining free times")
	busy_agenda = Agenda()
	for busy_time in busy_times:
		start, end = busy_time
		start = arrow.get(start)
		end = arrow.get(end)
		busy_agenda.append(Appt(start, end, ""))
	
	busy_agenda.normalize()
	free_start = arrow.get(free_start)
	free_end = arrow.get(free_end)
	free_block = Appt(free_start, free_end, "")
	free_agenda = busy_agenda.complement(free_block)
	
	free_times = [appt.get_isoformat() for appt in free_agenda]
	
	return free_times		
	
####
#
#  Google calendar authorization:
#      Returns us to the main /choose screen after inserting
#      the calendar_service object in the session state.  May
#      redirect to OAuth server first, and may take multiple
#      trips through the oauth2 callback function.
#
#  Protocol for use ON EACH REQUEST: 
#     First, check for valid credentials
#     If we don't have valid credentials
#         Get credentials (jump to the oauth2 protocol)
#         (redirects back to /choose, this time with credentials)
#     If we do have valid credentials
#         Get the service object
#
#  The final result of successful authorization is a 'service'
#  object.  We use a 'service' object to actually retrieve data
#  from the Google services. Service objects are NOT serializable ---
#  we can't stash one in a cookie.  Instead, on each request we
#  get a fresh serivce object from our credentials, which are
#  serializable. 
#
#  Note that after authorization we always redirect to /choose;
#  If this is unsatisfactory, we'll need a session variable to use
#  as a 'continuation' or 'return address' to use instead. 
#
####

def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(flask.session['credentials'])

    if (credentials.invalid or credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service

@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('respond_gcal'))

#####
#
#  POST routing methods. Receiving a lot of data from the user from fields
#
#####

@app.route('/create_meeting', methods=['POST'])
def create_meeting():
	'''
	Create a meeting in the DB based on user filled out fields
	'''
	app.logger.debug("Entering create_meeting")
	title = request.form.get('title')
	proposer = request.form.get('proposer')
	desc = request.form.get('desc')
	daterange = request.form.get('daterange')
	begin_time = request.form.get('begin_time')
	end_time = request.form.get('end_time')
	
	start_date, end_date = daterange.split(' - ')
	
	proposal = {
		"type": "proposal",
		"start_date": start_date,
		"end_date": end_date,
		"start_time": begin_time,
		"end_time": end_time,
		"proposer_name": proposer,
		"desc": desc,
		"title": title
	}
	meeting = proposal_collection.insert_one(proposal)
	id = str(meeting.inserted_id)
	return flask.redirect(flask.url_for("proposal_created", meeting_id=id))
    
@app.route('/submit_manual_times', methods=['POST'])
def submit_maunal_times():
	'''
	Check the date/time fields and create DB records based on them
	'''
	app.logger.debug("Entering submit_manual_times")
	user_name = request.form.get('user_name')	
	
	date = 1
	i = 0
	while date != None:
		date_name = "date" + str(i)
		start_name = "start_time" + str(i)
		end_name = "end_time" + str(i)
		date = request.form.get(date_name)
		start_time = request.form.get(start_name)
		end_time = request.form.get(end_name)
		
		if date == "":
			break
		
		start_date_time = arrow.get(date + start_time, "MM/DD/YYYYHH:mm")
		end_date_time = arrow.get(date + end_time, "MM/DD/YYYYHH:mm")
		meeting_id = ObjectId(flask.session['current_meeting']['_id'])
		
		record = {
			"type": "busy_time",
			"proposal_ID": meeting_id,
			"start": start_date_time.isoformat(),
			"end": end_date_time.isoformat(),
			"name": user_name
		   }
		busy_collection.insert_one(record)			
		i += 1
	return flask.redirect(flask.url_for("thanks"))
	
####
#
#  Functions (NOT pages) that return some information
#
####
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict, so that
    it can be stored in the session object and converted to
    json for cookies. The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)


def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])
    

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()
    
    
def init_proposals():
	'''
	Initialize the flask session variable for 'proposals'. 
	'''
	proposals = []
	for record in proposal_collection.find( {"type":"proposal" } ):		
		record['_id'] = str(record['_id'])
		proposals.append(record)
	flask.session['proposals'] = proposals	
	
def init_meeting_variables(meeting_id):
	'''
	Initializes the flask session variables to display meeting details.
	Includes current_meeting, daterange, begin and end time, names (of respondents), and
	available times
	'''
	meeting_id = ObjectId(meeting_id)
	meeting = proposal_collection.find_one( {"_id":meeting_id} )
	meeting['_id'] = str(meeting['_id'])
	flask.session['current_meeting'] = meeting
	flask.session['daterange'] = meeting['start_date'] + " - " + meeting['end_date']
	flask.session['begin_time'] = arrow.get(meeting['start_time'], "HH:mm").replace(tzinfo=tz.tzlocal()).isoformat().split("T")[1]
	flask.session['end_time'] = arrow.get(meeting['end_time'], "HH:mm").replace(tzinfo=tz.tzlocal()).isoformat().split("T")[1]
	
	# Set the names of the respondents
	names = []	
	busy_times = busy_collection.find( {"proposal_ID": meeting_id} )
	for record in busy_times:
		if record['name'] not in names:
			names.append(record['name'])	
	flask.session['names'] = names
	
	# Set the available times based on the busy times
	busy = []	
	busy_times = busy_collection.find( {"proposal_ID": meeting_id} )
	for record in busy_times:
		start = arrow.get(record['start']).replace(tzinfo=tz.tzlocal()).isoformat()
		end = arrow.get(record['end']).replace(tzinfo=tz.tzlocal()).isoformat()
		busy.append([start, end])
	
	start_date, end_date = flask.session['daterange'].split(" - ")
	time_range_start = arrow.get(start_date + flask.session['begin_time'], "MM/DD/YYYYHH:mm:ssZZ")
	time_range_end = arrow.get(start_date + flask.session['end_time'], "MM/DD/YYYYHH:mm:ssZZ")
	end_date = arrow.get(end_date, "MM/DD/YYYY")
	
	available = []	
	range = arrow.Arrow.span_range('day', time_range_start, end_date)
	for day in range:
		available.extend(determine_free_times(busy, time_range_start.isoformat(), time_range_end.isoformat()))
		time_range_start = time_range_start.replace(days=+1)
		time_range_end = time_range_end.replace(days=+1)	
	flask.session['available_times'] = available
	
	return None
    
    
#################
#
# Favicon function rendering
#
#################
  
@app.route('/favicon.ico')
def favicon():
    return flask.send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"
        
@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get(time, "HH:mm:ssZZ")
        return normal.format("hh:mm A")
    except:
        return "(bad time)"

        
@app.template_filter( 'fmtdatetime' )
def format_arrow_datetime( datetime ):
    try:
        normal = arrow.get(datetime)
        return normal.format("MM/DD/YYYY hh:mm A")
    except:
        return "(bad time)"
    
#############


if __name__ == "__main__":
  # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running in a CGI script)

  app.secret_key = str(uuid.uuid4())  
  app.debug=CONFIG.DEBUG
  app.logger.setLevel(logging.DEBUG)
  # We run on localhost only if debugging,
  # otherwise accessible to world
  if CONFIG.DEBUG:
    # Reachable only from the same computer
    app.run(port=CONFIG.PORT)
  else:
    # Reachable from anywhere 
    app.run(port=CONFIG.PORT,host="0.0.0.0")
    
