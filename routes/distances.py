import json
import os
import boto3
import urllib3

from flask import Blueprint, request
from boto3.dynamodb.conditions import Key
from urllib import parse

requests = urllib3.PoolManager()
dynamodb = boto3.resource('dynamodb')

GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

distances = Blueprint('distances', __name__)

def get_map_distance(homeAddress, loc_id, rawAddress, cache_locations=False):
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

@distances.route("/distances",methods=['GET','POST'])
def get_distances():  
    cache_locations = request.headers.get('cache-locations') == 'true'
    body = request.get_json()

    result = body['addresses']
    home = body['home']
    
    for i in range(0, len(result)):
        apptDistance, apptRawDistance = get_map_distance(
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
