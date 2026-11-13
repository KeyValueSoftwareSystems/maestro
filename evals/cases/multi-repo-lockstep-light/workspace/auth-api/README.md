# auth-api

Owns sign-in codes. `auth/otp.py::issue_code` backs `POST /otp`, which returns
`{"code_length": 5}` and sends the code by text message; `auth/otp.py::verify_code` backs
`POST /otp/verify`, which takes `{"code": "<digits>"}` as a string. The auth-cli client calls both.
