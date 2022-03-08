from flask import Flask, jsonify, make_response, request
import pytz
from datetime import datetime
import time
import json
import os
import re

import boto3
from boto3.dynamodb.conditions import Key

import urllib3
from urllib import parse

app = Flask(__name__)

dynamodb = boto3.resource('dynamodb')
s3 = boto3.resource('s3')
requests = urllib3.PoolManager()

headers = {
    'authority': 'sync-cf2-1.canimmunize.ca',
    'accept': 'application/json, text/plain, */*',
    'origin': 'https://novascotia.flow.canimmunize.ca',
    'referer': 'https://novascotia.flow.canimmunize.ca/',
}

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

BUCKET_NAME = os.getenv('SAVED_VACCINE_DATA_BUCKET')


@app.route("/locations",methods=['GET'])
def locations():    

    # query string
    getAllLocations = request.args.get('all') == 'true'
    test_mode = request.headers.get('test-mode') == 'true'
    
    if test_mode:
        # Load sample data
        content_object = s3.Object(BUCKET_NAME, 'locations.json')
        file_content = content_object.get()['Body'].read().decode('utf-8')
        allLocs = json.loads(file_content)
    else:
        # Request actual locations data
        locationsUrl = 'https://sync-cf2-1.canimmunize.ca/fhir/v1/public/booking-page/17430812-2095-4a35-a523-bb5ce45d60f1/appointment-types?forceUseCurrentAppointment=false&preview=false'
        response = requests.request("GET", locationsUrl, headers=headers)
        allLocs = json.loads( response.data )['results']
        
    adultLocs = list(filter(lambda x: x.get('maxAge') is None, allLocs))
    
    openLocs = list(filter(lambda x: not x.get('fullyBooked', True), adultLocs))
    
    hrmLocs = list(filter(lambda x: x.get('gisLocationString','').split(', ')[3] == 'Halifax County', openLocs))
    
    if getAllLocations:
        myLocs = openLocs
    else:
        myLocs = hrmLocs
    
    # ----------------------
    # Remove glitch location at Spryfield Pharmacy 564 Glen Alan Rd
    # ----------------------
    # glitchLocationId = 'c3c4e5ed-2c7f-4288-af65-1ecca316a771'
    # glitchIndex = next(i for i in range(0, len(myLocs)) if myLocs[i]['id'] == glitchLocationId)
    # if glitchIndex == None:
    #     myLocs.pop(glitchIndex)
    
    for loc in myLocs:
        loc['distance'] = '-'
        
        # Vaccine Field
        clinicName = loc['clinicName'].split(' - ')
        if len(clinicName) == 3:
            loc['vaccine'] = clinicName[2]
            shortName = clinicName[1]
        else:
            loc['vaccine'] = '-'
            shortName = loc['clinicName']
            
        # Address Field
        if 'https://' in loc.get('mapsLocationString',''):
            loc['address'] = loc.get('gisLocationString','')
        else:
            # Remove building name before streetname if the match includes
            #  more than just the postal code
            addressMatch = re.search('(\d+.*)', loc.get('mapsLocationString','')).group()
            if len(addressMatch) > 7:
                loc['address'] = addressMatch
            else:
                loc['address'] = loc.get('mapsLocationString','')
            
        # Name Field
        if 'COVID-19 Community Clinic' in loc.get('clinicName',''):
            loc['shortName'] = loc.get('durationDisplayEn','')
        else:
            loc['shortName'] = re.sub(r'\s\(.*\)', '', shortName)
            
        # Remove address from shortName field if necessary
        # TODO uncomment
        # street = loc['address'].split(' NS')[0]
        # if street in loc['shortName']:
        #     loc['shortName'] = loc['shortName'].replace(street, '')
        

    return {
        'locationCount': len(allLocs),
        'openCount': len(openLocs),
        'hrmCount': len(hrmLocs),
        'locations': myLocs,
    }
 
    # return jsonify(success=True, data=data)
def getDistance(homeAddress, loc_id, rawAddress, cache_locations=False):
    table = dynamodb.Table('clinic-distances')
    
    directionsURL = 'https://maps.googleapis.com/maps/api/directions/json?{}'
    params = {
        'origin': homeAddress,
        'destination': rawAddress,
        'key': GOOGLE_MAPS_API_KEY
    }
    
    if cache_locations:
        query = table.query(
            KeyConditionExpression=Key('id').eq(loc_id),
        )
        
        if len(query['Items']) != 0:
            distance = query['Items'][0]['distance']
            rawDistance = int(query['Items'][0]['rawDistance'])
            
            return distance, rawDistance
        
    urlParams = parse.urlencode(params)
    response = requests.request("GET", directionsURL.format(urlParams))

    distanceObj = json.loads( response.data )['routes'][0]['legs'][0]['distance']
    
    distance = distanceObj['text']
    rawDistance = int(distanceObj['value'])
    
    table.put_item(
        Item={ 
            'id': loc_id,
            'distance': distance,
            'rawDistance': rawDistance
        }
    )
    return distance, rawDistance

@app.route("/distances",methods=['GET','POST'])
def distances():  
    cache_locations = request.headers.get('cache-locations') == 'true'
    body = request.get_json()

    result = body['addresses']
    home = body['home']
    
    for i in range(0, len(result)):
        apptDistance, apptRawDistance = getDistance(
            home, 
            result[i]['id'], 
            result[i]['mapsLocationString'],
            cache_locations
        )
        result[i]['distance'] = apptDistance
        result[i]['rawDistance'] = apptRawDistance
    
    return {
        'count': len(result),
        'distances': result
    }


def dst_offset_atlantic():
    dt = datetime.utcnow()
    timezone = pytz.timezone('Canada/Atlantic')
    timezone_aware_date = timezone.localize(dt, is_dst=None)
    
    isDST = timezone_aware_date.tzinfo._dst.seconds != 0

    return 3 if isDST else 4

def getLocal(utc_datetime):
    date = datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    now_timestamp = time.time()
    offset = datetime.fromtimestamp(now_timestamp) - datetime.utcfromtimestamp(now_timestamp)
    localDate = date + offset
    hours = int(localDate.strftime("%H")) - dst_offset_atlantic()
    hourString = str(hours if hours <= 12 else hours - 12)
    timeSuffix = ' am' if hours < 12 else ' pm'
    return localDate.strftime("%b %d")+ ', ' + hourString + localDate.strftime(":%M") + timeSuffix
 
def parseAppts(loc_id, appts):
    myAppts = []
    apptCount = 0
    
    
    for appt in appts:
            
        apptCount += 1
        apptTime = appt['time']

        obj = {}
        obj['utcTime'] = apptTime
        obj['apptTime'] = getLocal(apptTime)

        myAppts.append(obj)
        myAppts.sort(key=lambda x: x['utcTime'])

    return {
        'id': loc_id,
        'earliest': myAppts[0],
        'appts': myAppts,
        # 'allAppts': myAppts,
    }, apptCount
  
@app.route("/appointments",methods=['GET','POST'])
def appointments():  
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

            apptData, newAppts = parseAppts(loc_id, appts)
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
            
            apptData, newAppts = parseAppts(loc_id, appts)
            apptCount += newAppts
            result.append(apptData)

            # Add appts to S3
            #
            # apptsArray = list(map(lambda x : x['time'], appts))
            # apptString = '{"appts":["'+ '","'.join(apptsArray) +'"]}'
            # object = s3.Object(BUCKET_NAME, f'{id}.json')
            # s3_result = object.put(Body=apptString)            

    return {
        'count': len(result),
        'apptCount': apptCount,
        'allAppts': result
    }


@app.errorhandler(404)
def resource_not_found(e):
    return make_response(jsonify(error='Not found!'), 404)
