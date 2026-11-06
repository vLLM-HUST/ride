"""Versioned JSON object/action contracts; no engine or execution dependency."""
import copy,hashlib,math,time
from .journal import canonical

OBJECT_SCHEMA='ride.object/v1'
ACTION_SCHEMA='ride.action/v1'
RESULT_SCHEMA='ride.action-result/v1'
KINDS=('Service','InstancePool','Instance','ResourceBinding','RuntimeState','Program','KVState')

class ActionConflict(ValueError):
    """A local authoritative precondition changed; no transition was committed."""


def text(value, label, maximum=256):
    if not isinstance(value,str) or not value or len(value)>maximum:
        raise ValueError('Explicit bounded '+label+' required')
    return value


def object_reference(kind,name,uid):
    if kind not in KINDS:raise ValueError('Unsupported object kind')
    text(name,'object name',128)
    if uid is not None:text(uid,'object UID')
    return dict(kind=kind,name=name,uid=uid)


def reference(value):
    if not isinstance(value,dict) or set(value)!={'kind','name','uid'}:
        raise ValueError('Exact object reference required')
    return object_reference(**value)


def validate_snapshot(value):
    fields={'schema','object','owner_id','owner_uid','resource_version','observed_at','state','observations'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=OBJECT_SCHEMA:
        raise ValueError('Versioned object snapshot required')
    reference(value['object']);text(value['owner_id'],'owner identity',128);text(value['owner_uid'],'owner UID',128)
    text(value['resource_version'],'resource version',128)
    if type(value['observed_at']) not in (int,float) or not math.isfinite(value['observed_at']):
        raise ValueError('Finite observation timestamp required')
    if not isinstance(value['state'],dict) or not isinstance(value['observations'],dict):
        raise ValueError('Separate persisted state and sampled observations required')
    canonical(value)
    return value


def make_snapshot(kind,name,uid,owner_id,owner_uid,version,state,observations):
    value=dict(schema=OBJECT_SCHEMA,object=object_reference(kind,name,uid),owner_id=owner_id,owner_uid=owner_uid,
        resource_version=version,observed_at=time.time(),state=copy.deepcopy(state),observations=copy.deepcopy(observations))
    return validate_snapshot(value)


def validate_action(value):
    fields={'schema','operation_id','actor_id','owner_id','owner_uid','target','expected_resource_version','action','parameters'}
    if not isinstance(value,dict) or set(value)!=fields or value['schema']!=ACTION_SCHEMA:
        raise ValueError('Versioned action envelope required')
    reference(value['target']);text(value['operation_id'],'operation identity',192)
    text(value['actor_id'],'actor identity',128);text(value['owner_id'],'owner identity',128);text(value['owner_uid'],'owner UID',128)
    text(value['expected_resource_version'],'expected resource version',128)
    text(value['action'],'action',64)
    if not isinstance(value['parameters'],dict):raise ValueError('Action parameters must be an object')
    canonical(value)
    return value


def make_action(snapshot,action,parameters,*,operation_id,actor_id):
    validate_snapshot(snapshot)
    value=dict(schema=ACTION_SCHEMA,operation_id=operation_id,actor_id=actor_id,
        owner_id=snapshot['owner_id'],owner_uid=snapshot['owner_uid'],target=copy.deepcopy(snapshot['object']),
        expected_resource_version=snapshot['resource_version'],action=action,parameters=copy.deepcopy(parameters))
    return validate_action(value)


def request_sha256(request):return hashlib.sha256(canonical(validate_action(request)).encode()).hexdigest()


def verify_action_result(request,result):
    validate_action(request)
    if (not isinstance(result,dict) or result.get('schema')!=RESULT_SCHEMA
            or result.get('operation_id')!=request['operation_id'] or result.get('actor_id')!=request['actor_id']
            or result.get('owner_id')!=request['owner_id'] or result.get('owner_uid')!=request['owner_uid'] or result.get('action')!=request['action']
            or result.get('target')!=request['target'] or result.get('request_sha256')!=request_sha256(request)
            or not isinstance(result.get('result'),dict)):
        raise ValueError('Action receipt identity/payload conflict')
    reference(result['object']);text(result['resource_version'],'result resource version',128)
    if (result.get('before_resource_version')!=request['expected_resource_version']
            or type(result.get('recorded_at')) not in (int,float) or not math.isfinite(result['recorded_at'])):
        raise ValueError('Action receipt version/time conflict')
    if result['object']['kind']!=request['target']['kind'] or result['object']['name']!=request['target']['name']:
        raise ValueError('Action receipt object conflict')
    canonical(result)
    return result
