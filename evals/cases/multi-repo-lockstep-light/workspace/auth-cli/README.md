# auth-cli

The command-line sign-in. Calls auth-api `POST /otp`, then asks for the code with
`cli/prompt.py::read_code` and sends it to `POST /otp/verify`.
