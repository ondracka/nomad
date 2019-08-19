import json

from nomad import infrastructure
from nomad import processing

    
infrastructure.setup_logging()
calcs = infrastructure.setup_mongo().fairdi_nomad_migration.calc
uploads = infrastructure.setup_mongo().fairdi_nomad_migration.upload
packages = infrastructure.setup_mongo().coe_migration.package


def retrieve_remote_data():

    count = 0
    pid_dict = {}

    for calc in calcs.find({'metadata.pid': {'$exists': True}}, {'metadata.pid': 1, 'upload_id': 1}):
        pid = calc['metadata']['pid']
        upload = calc['upload_id']

        pid_calcs = pid_dict.get(pid)
        if pid_calcs is None:
            pid_calcs = []
            pid_dict[pid] = pid_calcs

        if upload != 'j-IVBd3MQWWvTJ6pg5oaSw':
            pid_calcs.append(upload)

        count += 1
        if count % 100000 == 0:
            print(count)

    with open('pid_dict.json', 'wt') as f:
        json.dump(pid_dict, f)

    return pid_dict


def load_local_data():
    with open('pid_dict.json', 'rt') as f:
        return json.load(f)


try:
    pid_dict = load_local_data()
except Exception:
    pid_dict = retrieve_remote_data()

print('data available ...')


def remove_upload(upload):
    for uploads in pid_dict.values():
        if upload in uploads:
            uploads.remove(upload)


def calc_dups():
    upload_dict = {}
    for _, uploads in pid_dict.items():
        uploads = list(set(uploads))
        for upload in uploads:
            dup, single = upload_dict.get(upload, (0, 0))
            if len(uploads) >= 2:
                dup += 1
            else:
                single += 1
            upload_dict[upload] = (dup, single)

    return upload_dict


more = False
while True:
    upload_dict = calc_dups()
    for upload, (dup, single) in upload_dict.items():
        if single == 0:
            print('full: ' + upload)
            remove_upload(upload)
            more = True
            break

    if not more:
        for upload, (dup, single) in upload_dict.items():
            if dup > 0:
                package_id = uploads.find_one({'_id': upload})['name']        
                pkg = packages.find_one({'_id': package_id})
                source_upload_id = pkg['upload_id']
                pkg_path = pkg['package_path']
                print('%s, %s, %s, %s (%d vs %d)' % (source_upload_id, package_id, pkg_path, upload, dup, single))
        break