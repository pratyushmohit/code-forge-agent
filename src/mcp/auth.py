import boto3


def get_temporary_credentials(duration_seconds: int = 3600) -> dict:
    sts = boto3.client("sts")
    try:
        response = sts.get_session_token(DurationSeconds=duration_seconds)
    except Exception as e:
        raise RuntimeError(f"Failed to obtain STS credentials: {e}")

    creds = response["Credentials"]
    return {
        "access_key_id": creds["AccessKeyId"],
        "secret_access_key": creds["SecretAccessKey"],
        "session_token": creds["SessionToken"],
        "expiry": creds["Expiration"].isoformat(),
    }
