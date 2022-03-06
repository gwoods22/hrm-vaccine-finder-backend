
import time
import json
import os
import re

import boto3
from boto3.dynamodb.conditions import Key

import urllib3
from urllib import request, parse

from full import fullRequest

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

BUCKET_NAME = 'graeme-testing-bucket-ywzyhwhc2zz'

CACHE_LOCATIONS = False

# Current Atlantic timezone offset
#  3 in the summer, 4 in the winter
DAYLIGHT_TIME_OFFSET = 4

dynamodb = boto3.resource('dynamodb')
s3 = boto3.resource('s3')
requests = urllib3.PoolManager()

headers = {
    'authority': 'sync-cf2-1.canimmunize.ca',
    'accept': 'application/json, text/plain, */*',
    'origin': 'https://novascotia.flow.canimmunize.ca',
    'referer': 'https://novascotia.flow.canimmunize.ca/',
}

def getLocal(utc_datetime):
    date = datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    now_timestamp = time.time()
    offset = datetime.fromtimestamp(now_timestamp) - datetime.utcfromtimestamp(now_timestamp)
    localDate = date + offset
    hours = int(localDate.strftime("%H")) - DAYLIGHT_TIME_OFFSET
    hourString = str(hours if hours <= 12 else hours - 12)
    timeSuffix = ' am' if hours < 12 else ' pm'
    return localDate.strftime("%b %d")+ ', ' + hourString + localDate.strftime(":%M") + timeSuffix
    
def getDistance(homeAddress, id, rawAddress):
    table = dynamodb.Table('clinic-distances')
    
    directionsURL = 'https://maps.googleapis.com/maps/api/directions/json?{}'
    params = {
        'origin': homeAddress,
        'destination': rawAddress,
        'key': GOOGLE_MAPS_API_KEY
    }
    
    if CACHE_LOCATIONS:
        query = table.query(
            KeyConditionExpression=Key('id').eq(id),
        )
        
        if len(query['Items']) != 0:
            distance = query['Items'][0]['distance']
            rawDistance = query['Items'][0]['rawDistance']
            
            return distance, rawDistance
        
    urlParams = parse.urlencode(params)
    response = requests.request("GET", directionsURL.format(urlParams))

    distanceObj = json.loads( response.data )['routes'][0]['legs'][0]['distance']
    
    distance = distanceObj['text']
    rawDistance = distanceObj['value']
    
    table.put_item(
        Item={ 
            'id': id,
            'distance': distance,
            'rawDistance': rawDistance
        }
    )
    return distance, rawDistance

def lambda_handler(event, context):
    route = event['params']['path']['command']
    allLocations = event['params']['querystring'].get('all') == 'true'
    
    headers = event['params']['header']
    
    test_mode = headers.get('test-mode') == 'true'
    
    body = event['body-json']
    
    if route == 'locations':
        return locations(allLocations,test_mode)
        
    elif route == 'distance':
        return distances(body)
        
    elif route == 'appointments':
        if test_mode:
            return testAppointments(body)
        else:
            return realAppointments(body)
        
    elif route == 'full':
        return fullRequest()
    
    return {
        'errorMessage': 'Invalid request route',
        'errorType': 'PATH ERROR',
        'Route': route 
    }

def locations(all,test_mode):
    
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
    
    # For now always return all locations
    # 
    # if all:
    #     myLocs = openLocs
    # else:
    #     myLocs = hrmLocs
    myLocs = openLocs
    
    # # Remove glitch location at Spryfield Pharmacy 564 Glen Alan Rd
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
            
        # Tried to remove address from name field
        #
        # street = loc['address'].split(' NS')[0]
        # if street in loc['shortName']:
        #     loc['shortName'] = loc['shortName'].replace(street, '')
        

    return {
        'locationCount': len(allLocs),
        'openCount': len(openLocs),
        'hrmCount': len(hrmLocs),
        'locations': myLocs,
    }
    
def distances(body):
    result = body['addresses']
    home = body['home']
    
    for i in range(0, len(result)):
        apptDistance, apptRawDistance = getDistance(home, result[i]['id'], result[i]['mapsLocationString'])
        result[i]['distance'] = apptDistance
        result[i]['rawDistance'] = apptRawDistance
    
    return {
        'count': len(result),
        'distances': result
    }

def testAppointments(body):
    # array of location ID's
    ids = body['ids']
    
    table = dynamodb.Table('vaccine-appointments')
    
    result = []
    apptCount = 0
    
    activeLocationCount = 0
    
    for id in ids:
        query = table.query(
            IndexName='locationID-index',
            KeyConditionExpression=Key('locationID').eq(id),
        )
        
        if query['Count'] == 0:
            return {
                'errorMessage': 'No availabile appointments found.',
                'errorType': 'REQUEST ERROR',
                'id': id 
            }
            
        activeLocationCount += 1
        
        appts = query['Items']
        
        myAppts = []
        
        for appt in appts:
            apptCount += 1
            apptTime = appt['apptTime']
    
            obj = {}
            obj['utcTime'] = apptTime
            obj['apptTime'] = getLocal(apptTime)
    
            myAppts.append(obj)
            myAppts.sort(key=lambda x: x['utcTime'])
    
        result.append({
            'id': id,
            'earliest': myAppts[0],
            'appts': myAppts,
        })

    return {
        'count': len(result),
        'apptCount': apptCount,
        'appts': result
    }

def realAppointments(body):
    # array of location ID's
    ids = body['ids']
    
    apptsUrl = 'https://sync-cf2-1.canimmunize.ca/fhir/v1/public/availability/17430812-2095-4a35-a523-bb5ce45d60f1?appointmentTypeId={}&timezone=America%2FHalifax&preview=false'
    
    result = []
    apptCount = 0
    
    activeLocationCount = 0
    
    for id in ids:
        # # Prevent timeouts by capping appointment locations to 50
        # if activeLocationCount > 50:
        #     result.append({
        #         'id': id,
        #         'earliest': 'Over 50',
        #         'appts': [],
        #     })
        #     break
        
        url = apptsUrl.format(id)
        response = requests.request("GET", url, headers=headers)
        if len(json.loads( response.data )) == 0:
            return {
                'errorMessage': 'No availabile appointments found.',
                'errorType': 'REQUEST ERROR',
                'id': id 
            }
        
        activeLocationCount += 1
        
        appts = json.loads( response.data )[0]['availabilities']
        
        # Add appts to S3
        #
        # apptsArray = list(map(lambda x : x['time'], appts))
        # apptString = '{"appts":["'+ '","'.join(apptsArray) +'"]}'
        # object = s3.Object(BUCKET_NAME, f'{id}.json')
        # s3_result = object.put(Body=apptString)
        
        myAppts = []
        
        for appt in appts:
                
            apptCount += 1
            apptTime = appt['time']
    
            obj = {}
            obj['utcTime'] = apptTime
            obj['apptTime'] = getLocal(apptTime)
    
            myAppts.append(obj)
            myAppts.sort(key=lambda x: x['utcTime'])
    
        result.append({
            'id': id,
            'earliest': myAppts[0],
            'appts': myAppts,
        })

    return {
        'count': len(result),
        'apptCount': apptCount,
        'appts': result
    }