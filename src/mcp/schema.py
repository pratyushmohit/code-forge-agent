import botocore.session


def get_condensed_service_schema(service_name: str) -> dict:
    session = botocore.session.get_session()
    try:
        service_model = session.get_service_model(service_name)
    except Exception as e:
        raise ValueError(f"Unknown AWS service '{service_name}': {e}")

    operations = {}
    for op_name in service_model.operation_names:
        op_model = service_model.operation_model(op_name)
        input_shape = op_model.input_shape
        params = {}
        if input_shape:
            for member_name, member_shape in input_shape.members.items():
                params[member_name] = member_shape.type_name
        operations[op_name] = {"input": params}

    return {"service": service_name, "operations": operations}
