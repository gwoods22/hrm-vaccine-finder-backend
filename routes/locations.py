import json
import os
import re
import boto3
import urllib3

from flask import Blueprint, request

s3 = boto3.resource('s3')
requests = urllib3.PoolManager()

locations = Blueprint('locations', __name__)

headers = {
    'authority': 'sync-cf2-1.canimmunize.ca',
    'accept': 'application/json, text/plain, */*',
    'origin': 'https://novascotia.flow.canimmunize.ca',
    'referer': 'https://novascotia.flow.canimmunize.ca/',
}

BUCKET_NAME = os.getenv('SAVED_VACCINE_DATA_BUCKET')

@locations.route("/locations",methods=['GET'])
def get_locations():  
    """ Return vaccine appointment locations in Nova Scotia
    
    Returns:
        dict: Locations response object
    """
    getAllLocations = request.headers.get('all-locations') == 'true'
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