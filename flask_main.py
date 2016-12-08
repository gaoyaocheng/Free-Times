import flask
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify
import uuid

import json
import logging

import datetime
# Date handling
import arrow # Replacement for datetime, based on moment.js
# import datetime # But we still need time
from dateutil import tz  # For interpreting local times

from bson.objectid import ObjectId

from freeTimes import *

# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

import os
# Google API for services
from apiclient import discovery

###
# Globals
###
import CONFIG
import secrets.admin_secrets  # Per-machine secrets
import secrets.client_secrets # Per-application secrets

app = flask.Flask(__name__)
app.debug=CONFIG.DEBUG
app.logger.setLevel(logging.DEBUG)
app.secret_key=CONFIG.secret_key

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = secrets.admin_secrets.google_key_file  ## You'll need this
APPLICATION_NAME = 'CIS 322 project MeetMe'

import pymongo
from pymongo import MongoClient
MONGO_CLIENT_URL = "mongodb://{}:{}@localhost:{}/{}".format(
        secrets.client_secrets.db_user,
        secrets.client_secrets.db_user_pw,
        secrets.admin_secrets.port,
        secrets.client_secrets.db)

try:
    dbclient = MongoClient(MONGO_CLIENT_URL)
    db = getattr(dbclient, secrets.client_secrets.db)
    busy_table = db.busy
    meeting_table = db.proposal

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
    init_session();
    return render_template('index.html')

@app.route("/create_meeting")
def create_meeting():
    app.logger.debug("Entering create_meeting")
    return render_template('create_meeting.html')

@app.route("/meeting_created/<mid>")
def meeting_created(mid):
    app.logger.debug("Entering proposal_created")
    flask.session['mid'] = mid
    return render_template("meeting_created.html")

@app.route("/meeting_detail/<mid>")
def meeting_detail(mid):
    app.logger.debug("Entering meeting_detail")

    init_meeting(mid)
    return render_template('meeting_detail.html')

@app.route("/respond/<mid>")
def respond(mid):
    app.logger.debug("Entering respond")

    init_meeting(mid)
    return render_template('respond.html')


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

#####    ajax handler     ######
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
                busy_table.insert_one(record)

    return jsonify(result={})

@app.route('/do_create_meeting', methods=['POST'])
def do_create_meeting():
    '''
    Create meeting to mongo
    '''
    app.logger.debug("Entering do_create_meeting")

    title = request.form.get('title')
    proposer = request.form.get('proposer')
    desc = request.form.get('desc')
    start_date, end_date = request.form.get('daterange').split(' - ')
    begin_time = request.form.get('begin_time')
    end_time = request.form.get('end_time')

    meeting = {
        "type": "meeting",
        "title": title,
        "proposer_name": proposer,
        "desc": desc,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": begin_time,
        "end_time": end_time,
    }
    meeting = meeting_table.insert_one(meeting)
    return flask.redirect(flask.url_for("meeting_created", mid=str(meeting.inserted_id)))

@app.route("/_delete_meetings")
def delete_meetings():
    '''
    Delete a meeting from the DB
    '''
    app.logger.debug("Entering delete_meetings, AJAX handler")
    meeting_ids = request.args.get("meeting_ids", type=str)

    meeting_ids = meeting_ids.split(";")
    for id in meeting_ids:
        if id == "":
            continue
        id = ObjectId(id)
        meeting_table.delete_one( {"_id": id} )
        busy_table.delete_many( {"proposal_ID": id} )

    return jsonify(result={})

@app.route("/_setbusytimes")
def find_busy():
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

#@app.route("/choose")
#def choose():
#    ## We'll need authorization to list calendars
#    ## I wanted to put what follows into a function, but had
#    ## to pull it back here because the redirect has to be a
#    ## 'return'
#    credentials = valid_credentials()
#    if not credentials:
#        return flask.redirect(flask.url_for('oauth2callback'))
#
#    gcal_service = get_gcal_service(credentials)
#    calendars = list_calendars(gcal_service)
#    result = []
#    for cal in calendars:
#        cal['event'] = get_events(gcal_service, cal['id'])
#
#    flask.g.calendars = calendars
#
#    return render_template('index.html')

def get_freebusy_times(gcal_service, calendar_ids):
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
def valid_credentials():
    if 'credentials' not in flask.session:
        return None

    credentials = client.OAuth2Credentials.from_json(
            flask.session['credentials'])

    if (credentials.invalid or
            credentials.access_token_expired):
        return None
    return credentials


def get_gcal_service(credentials):
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  return service

@app.route('/oauth2callback')
def oauth2callback():
  flow =  client.flow_from_clientsecrets(
          CLIENT_SECRET_FILE,
          scope= SCOPES,
          redirect_uri=flask.url_for('oauth2callback', _external=True))
  if 'code' not in flask.request.args:
      auth_uri = flow.step1_get_authorize_url()
      return flask.redirect(auth_uri)
  else:
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    return flask.redirect(flask.url_for('respond_gcal'))


#
#   Initialize session variables
#

def init_session():
    '''
    init flask session
    '''
    meetings = []
    for item in meeting_table.find( {"type":"meeting" } ):
        item['_id'] = str(item['_id'])
        meetings.append(item)
    flask.session['meetings'] = meetings

def init_meeting(mid):
    mid = ObjectId(mid)
    meeting = meeting_table.find_one( {"_id":mid} )
    meeting['_id'] = str(meeting['_id'])
    flask.session['daterange'] = meeting['start_date'] + " - " + meeting['end_date']
    flask.session['current_meeting'] = meeting
    flask.session['begin_time'] = arrow.get(meeting['start_time'], "HH:mm").replace(tzinfo=tz.tzlocal()).isoformat().split("T")[1]
    flask.session['end_time'] = arrow.get(meeting['end_time'], "HH:mm").replace(tzinfo=tz.tzlocal()).isoformat().split("T")[1]

    names = []
    busy = []
    busy_times = busy_table.find( {"proposal_ID": mid} )
    for item in busy_times:
        if item['name'] not in names:
            names.append(item['name'])

        start = arrow.get(item ['start']).replace(tzinfo=tz.tzlocal()).isoformat()
        end = arrow.get(item['end']).replace(tzinfo=tz.tzlocal()).isoformat()
        busy.append({'start':start, 'end':end})

    flask.session['names'] = names

    start_date, end_date = flask.session['daterange'].split(" - ")
    time_range_start = arrow.get(start_date + flask.session['begin_time'], "MM/DD/YYYYHH:mm:ssZZ")
    time_range_end = arrow.get(start_date + flask.session['end_time'], "MM/DD/YYYYHH:mm:ssZZ")
    end_date = arrow.get(end_date, "MM/DD/YYYY")

    freetime = []
    range = arrow.Arrow.span_range('day', time_range_start, end_date)
    for day in range:
        freetime.extend(determine_free_times(busy, time_range_start.isoformat(), time_range_end.isoformat()))
        time_range_start = time_range_start.replace(days=+1)
        time_range_end = time_range_end.replace(days=+1)

    flask.session['free_times'] =  freetime;
    return None


def interpret_time( text ):
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try:
        as_arrow = arrow.get(text, time_formats).replace(tzinfo=tz.tzlocal())
        as_arrow = as_arrow.replace(year=2016) #HACK see below
    except:
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
                .format(text))
        raise
    return as_arrow.isoformat()

def interpret_date( text ):
    try:
        as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
                tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

def get_events(service, calenderid):
    start = flask.session['begin_date'] ;
    end = flask.session['end_date'] ;
    beginTime = arrow.get(flask.session['begin_time'])
    endTime = arrow.get(flask.session['end_time'])
    if start == end:
        end = next_day(start)
    eventsResult = service.events().list(
            calendarId=calenderid, timeMin=start, timeMax=end, singleEvents=True,

            orderBy='startTime').execute()
    events = eventsResult.get('items', [])
    result = []

    for event in events:
        if 'transparency' in event:
            continue
        event_start = arrow.get(event['start'].get('dateTime', event['start'].get('date')))
        event_end = arrow.get(event['end'].get('dateTime', event['end'].get('date')))
        choose_start = replaceHM(arrow.get(event_start), beginTime.hour, beginTime.minute)
        choose_end = replaceHM(arrow.get(event_end), endTime.hour, endTime.minute)

        if event_start >= choose_end or event_end <= choose_start:
            continue
        summary =  'no summary'
        if 'summary' in event:
            summary = event['summary']
        result.append(
                { "start": arrow.get(event_start).format('YYYY-MM-DD HH:mm'),
                    "end": arrow.get(event_end).format('YYYY-MM-DD HH:mm'),
                    "summary": summary,
                    "calendar" : eventsResult['summary']
                    })
        result = sorted(result, key = lambda k : k['start'])

    result = free_events(flask.session['begin_date'],
            flask.session['end_date'],
            flask.session['begin_time'],
            flask.session['end_time'],
            result)
    return result

def list_calendars(service):
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
    if cal["selected"]:
        selected_key = " "
    else:
        selected_key = "X"
    if cal["primary"]:
        primary_key = " "
    else:
        primary_key = "X"
    return (primary_key, selected_key, cal["summary"])


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
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"
@app.template_filter( 'fmtdatetime' )
def format_arrow_datetime( datetime ):
    try:
        normal = arrow.get(datetime)
        return normal.format("YYYY-MM-DD hh:mm")
    except:
        return "(bad time)"

#############


if __name__ == "__main__":
    # App is created above so that it will
  # exist whether this is 'main' or not
  # (e.g., if we are running under green unicorn)
  app.run(port=CONFIG.PORT,host="0.0.0.0")

