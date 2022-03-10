from flask import Flask, jsonify, make_response
from flask_cors import CORS

from routes.locations import locations
from routes.appointments import appointments
from routes.distances import distances

app = Flask(__name__)
app.register_blueprint(locations)
app.register_blueprint(appointments)
app.register_blueprint(distances)

cors = CORS(app)

@app.errorhandler(404)
def resource_not_found(e):
    return make_response(jsonify(error='Not found!'), 404)
