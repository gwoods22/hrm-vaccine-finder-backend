from datetime import datetime
import time
import json
import os

import urllib3
from urllib import request, parse

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

requests = urllib3.PoolManager()

def getLocal(utc_datetime):
    date = datetime.fromisoformat(utc_datetime.replace("Z", "+00:00"))
    now_timestamp = time.time()
    offset = datetime.fromtimestamp(now_timestamp) - datetime.utcfromtimestamp(now_timestamp)
    localDate = date + offset
    return localDate.strftime("%b %d %H:%M %p")
    
def getDistance(rawAddress):
    directionsURL = 'https://maps.googleapis.com/maps/api/directions/json?{}'
    params = {
        'origin': '5691 Inglis St, Halifax',
        'destination': rawAddress,
        'key': GOOGLE_MAPS_API_KEY
    }
    
    urlParams = parse.urlencode(params)
    
    response = requests.request("GET", directionsURL.format(urlParams))

    # distance = response.json()['routes'][0]['legs'][0]['distance']
    distanceObj = json.loads( response.data )['routes'][0]['legs'][0]['distance']
    
    distance = distanceObj['text']
    rawDistance = distanceObj['value']
    
    return distance, rawDistance

    
def fullRequest():
    locationsUrl = 'https://sync-cf2-1.canimmunize.ca/fhir/v1/public/booking-page/17430812-2095-4a35-a523-bb5ce45d60f1/appointment-types?forceUseCurrentAppointment=false&preview=false'

    payload={}
    headers = {
        'authority': 'sync-cf2-1.canimmunize.ca',
        'accept': 'application/json, text/plain, */*',
        'user-agent': 'Mozilla/5.0 (Macintosh',
        'origin': 'https://novascotia.flow.canimmunize.ca',
        'referer': 'https://novascotia.flow.canimmunize.ca/',
    }

    

    response = requests.request("GET", locationsUrl, headers=headers)

    # allAppts = response.json()['results']
    allAppts = json.loads( response.data )['results']
    
    openAppts = list(filter(lambda x: not x['fullyBooked'], allAppts))
    hrmAppts = list(filter(lambda x: x['gisLocationString'].split(', ')[3] == 'Halifax County', openAppts))

    myAppts = []
    
    counter = 0

    for i in range(1, len(hrmAppts)):
        counter += 1
        if counter > 10:
            break
        
        apptsUrl = 'https://sync-cf2-1.canimmunize.ca/fhir/v1/public/availability/17430812-2095-4a35-a523-bb5ce45d60f1?appointmentTypeId={}&timezone=America%2FHalifax&preview=false'
        url = apptsUrl.format(hrmAppts[i]['id'])

        response = requests.request("GET", url, headers=headers)

        clinicName = hrmAppts[i]['clinicName'].split(' - ')

        # appts = response.json()[0]['availabilities']
        appts = json.loads( response.data )[0]['availabilities']
        
        apptDistance, apptRawDistance = getDistance(hrmAppts[i]['gisLocationString'])
        
        for appt in appts:
            apptTime = appt['time']

            obj = {}
            obj['utcTime'] = apptTime
            obj['apptTime'] = getLocal(apptTime)
            obj['id'] = hrmAppts[i]['id']
            obj['address'] = hrmAppts[i]['gisLocationString']
            obj['distance'] = apptDistance
            obj['rawDistance'] = apptRawDistance
            
            if len(clinicName) == 3:
                obj['vaccine'] = clinicName[2],
                obj['name'] = clinicName[1]
            else:
                obj['name'] = ' '.join(clinicName)

            myAppts.append(obj)

    myAppts.sort(key=lambda x: x['utcTime'])

    return {
        'count': len(myAppts),
        'appts': myAppts,
    }