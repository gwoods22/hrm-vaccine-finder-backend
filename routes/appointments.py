import pytz
from datetime import datetime
import time
import json
import boto3
import urllib3

from flask import Blueprint, request
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource('dynamodb')
requests = urllib3.PoolManager()

headers = {
    'authority': 'sync-cf2-1.canimmunize.ca',
    'accept': 'application/json, text/plain, */*',
    'origin': 'https://novascotia.flow.canimmunize.ca',
    'referer': 'https://novascotia.flow.canimmunize.ca/',
}

appointments = Blueprint('appointments', __name__)

def dst_offset_atlantic():
    """ Determine if Atlantic timezone is in Daylight Savings Time

    Returns:
        int: current Atlantic offset including DST
    """
    dt = datetime.utcnow()
    timezone = pytz.timezone('Canada/Atlantic')
    timezone_aware_date = timezone.localize(dt, is_dst=None)
    
    isDST = timezone_aware_date.tzinfo._dst.seconds != 0

    return 3 if isDST else 4

def get_local(utc_datetime):
    """ Convert UTC datetime to Atlantic local time

    Parameters:
        utc_datetime (str): Datetime string to convert

    Returns:
        str: Locally formatted datetime string
    """
    date = datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    now_timestamp = time.time()
    offset = datetime.fromtimestamp(now_timestamp) - datetime.utcfromtimestamp(now_timestamp)
    localDate = date + offset
    hours = int(localDate.strftime("%H")) - dst_offset_atlantic()
    hourString = str(hours if hours <= 12 else hours - 12)
    timeSuffix = ' am' if hours < 12 else ' pm'
    return localDate.strftime("%b %d")+ ', ' + hourString + localDate.strftime(":%M") + timeSuffix
 
def parse_appts(loc_id, appts):
    """ Convert raw appointment data to minimal return format

    Parameters:
        loc_id (str): Location ID
        appts (dict[]): Array of appointment objects

    Returns:
        (dict, int): Tuple containing appointments object and appointment count
    """
    myAppts = []
    apptCount = 0
    
    
    for appt in appts:
            
        apptCount += 1
        apptTime = appt['time']

        obj = {}
        obj['utcTime'] = apptTime
        obj['apptTime'] = get_local(apptTime)

        myAppts.append(obj)
        myAppts.sort(key=lambda x: x['utcTime'])

    return {
        'id': loc_id,
        'earliest': myAppts[0],
        'allAppts': myAppts,
    }, apptCount
  
@appointments.route("/appointments",methods=['POST'])
def get_appointments():
    """ Return available vaccine appointments based on passed location IDs
    
    Returns:
        dict: Appointments response object
    """
    test_mode = request.headers.get('test-mode') == 'true'
    body = request.get_json()  

    # array of location ID's
    location_ids = body['ids']      
    
    result = []
    apptCount = 0
    
    activeLocationCount = 0

    if test_mode:
        table = dynamodb.Table('vaccine-appointments')

        for loc_id in location_ids:
            query = table.query(
                IndexName='locationID-index',
                KeyConditionExpression=Key('locationID').eq(loc_id),
            )
            
            if query['Count'] == 0:
                return {
                    'errorMessage': 'No availabile appointments found.',
                    'errorType': 'REQUEST ERROR',
                    'id': loc_id 
                }
            
            activeLocationCount += 1
        
            appts = query['Items']

            apptData, newAppts = parse_appts(loc_id, appts)
            apptCount += newAppts
            result.append(apptData)

    else:
        apptsUrl = 'https://sync-cf2-1.canimmunize.ca/fhir/v1/public/availability/17430812-2095-4a35-a523-bb5ce45d60f1?appointmentTypeId={}&timezone=America%2FHalifax&preview=false'
        
        for loc_id in location_ids:        
            url = apptsUrl.format(loc_id)
            response = requests.request("GET", url, headers=headers)
            if len(json.loads( response.data )) == 0:
                return {
                    'errorMessage': 'No availabile appointments found.',
                    'errorType': 'REQUEST ERROR',
                    'id': loc_id 
                }
            
            activeLocationCount += 1
            
            appts = json.loads( response.data )[0]['availabilities']
            
            apptData, newAppts = parse_appts(loc_id, appts)
            apptCount += newAppts
            result.append(apptData)

    return {
        'count': len(result),
        'apptCount': apptCount,
        'allAppts': result
    }
