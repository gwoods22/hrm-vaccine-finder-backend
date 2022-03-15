# HRM Vaccine Finder Backend

This is the backend of the HRM Vaccine Finder app available [here](https://github.com/gwoods22/hrm-vaccine-finder).

Some folks wouldn't call this a backend at all, it has no "server"! It's an AWS Lambda function written in Python triggered through an API Gateway deployed using the awesome [Serverless framework](https://github.com/serverless/serverless). It has 3 distinct routes, one for requesting vaccine appointment locations, one for getting the specific appointment times, and one for getting the distance between yourself and the location.
