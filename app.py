from flask import Flask, jsonify, make_response, request

app = Flask(__name__)

@app.route("/")
def hello():
    return {
        'text': 'Hello from root!'
    }


@app.errorhandler(404)
def resource_not_found(e):
    return make_response(jsonify(error='Not found!'), 404)
