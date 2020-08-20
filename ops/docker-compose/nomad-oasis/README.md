# Operating a NOMAD OASIS

The following describes the simplest way to run your own NOMAD.

## What is an OASIS

Originally NOMAD is a service run at Max-Planck's compute facility in Garching, Germany.
However, the NOMAD software is Open-Source and everybody can run it. We call any service that
uses NOMAD software independently a *NOMAD OASIS*.

While there are several use cases that require different setups, this documentations
describes the simples NOMAD OASIS setup possible. It will allow you to use NOMAD to
manage research data locally, while using NOMAD's central user-management and its users.

## Pre-requisites

NOMAD software is distributed as a set of docker containers. Further, other services
that can be run with docker are required. Further, we use docker-compose to setup
all necessary container in the simples possible manner.

You will need a single computer, with **docker** and **docker-compose** installed.

The following will run all necessary services with docker. These comprise: a **mongodb**
database, an **elasticsearch**, a **rabbitmq** distributed task queue, the NOMAD **app**,
NOMAD **worker**, and NOMAD **gui**. Refer to this [introduction](/app/docs/introduction.html#architecture)
to learn what each service does and why it is necessary.

There is also some information you need to configure your NOMAD OASIS:
- The hostname for the machine you run NOMAD on. This is important for redirects between
your OASIS and the central NOMAD user-management and to allow your users to upload files (via GUI or API).
Your machine needs to be accessible under this hostname from the public internet. The host
name needs to be registered with the central NOMAD in order to configure the central user-
management correctly.
- A NOMAD account that acts as an admin account for your OASIS. This account must be declared
to the central NOMAD as an OASIS admin in order to give it the necessary rights in the central user-
management.

## Configuration

All docker container are configured via docker-compose an the respective `docker-compose.yaml` file.
Further, we will need to mount some configuration files to configure the NOMAD services within
their respective containers.

Please [write us](mailto:support@nomad-lab.eu) to register your NOMAD account as an OASIS
admin and to register your hostname. Please replace the indicated configuration items with
the right information.

There are three files to configure:
- `docker-compose.yaml`
- `nomad.yaml`
- `env.js`
- `nginx.conf`

In this example, we have all files in the same directory (the directory we also work from).
You can download examples files from
[here](https://gitlab.mpcdf.mpg.de/nomad-lab/nomad-FAIR/tree/master/ops/docker-compose/nomad-oasis/).

### Docker compose

The most basic `docker-compose.yaml` to run an OASIS looks like this:

```yaml
version: '3.4'

x-common-variables: &nomad_backend_env
    NOMAD_RABBITMQ_HOST: rabbitmq
    NOMAD_ELASTIC_HOST: elastic
    NOMAD_MONGO_HOST: mongo

services:
    # broker for celery
    rabbitmq:
        restart: always
        image: rabbitmq:3.7.17
        container_name: nomad_oasis_rabbitmq
        environment:
            - RABBITMQ_ERLANG_COOKIE=SWQOKODSQALRPCLNMEQG
            - RABBITMQ_DEFAULT_USER=rabbitmq
            - RABBITMQ_DEFAULT_PASS=rabbitmq
            - RABBITMQ_DEFAULT_VHOST=/
        volumes:
            - nomad_oasis_rabbitmq:/var/lib/rabbitmq

    # the search engine
    elastic:
        restart: always
        image: docker.elastic.co/elasticsearch/elasticsearch:6.3.2
        container_name: nomad_oasis_elastic
        volumes:
            - nomad_oasis_elastic:/usr/share/elasticsearch/data

    # the user data db
    mongo:
        restart: always
        image: mongo:4
        container_name: nomad_oasis_mongo
        environment:
            - MONGO_DATA_DIR=/data/db
            - MONGO_LOG_DIR=/dev/null
        volumes:
            - nomad_oasis_mongo:/data/db
        command: mongod --logpath=/dev/null # --quiet

    # nomad worker (processing)
    worker:
        restart: always
        image: gitlab-registry.mpcdf.mpg.de/nomad-lab/nomad-fair:stable
        container_name: nomad_oasis_worker
        environment:
            <<: *nomad_backend_env
            NOMAD_SERVICE: nomad_oasis_worker
        links:
            - rabbitmq
            - elastic
            - mongo
        volumes:
            - ./nomad.yaml:/app/nomad.yaml
            - nomad_oasis_files:/app/.volumes/fs
        command: python -m celery worker -l info -A nomad.processing -Q celery,calcs,uploads

    # nomad app (api + gui)
    app:
        restart: always
        image: gitlab-registry.mpcdf.mpg.de/nomad-lab/nomad-fair:stable
        container_name: nomad_oasis_app
        environment:
            <<: *nomad_backend_env
            NOMAD_SERVICE: nomad_oasis_app
        links:
            - rabbitmq
            - elastic
            - mongo
        volumes:
            - ./nomad.yaml:/app/nomad.yaml
            - ./env.js:/app/gui/build/env.js
            - ./gunicorn.log.conf:/app/gunicorn.log.conf
            - ./gunicorn.conf:/app/gunicorn.conf
            - nomad_oasis_files:/app/.volumes/fs
        command: ["./run.sh", "/nomad-oasis"]

    # nomad gui (a reverse proxy for nomad)
    gui:
        restart: always
        image: nginx:1.13.9-alpine
        container_name: nomad_oasis_gui
        command: nginx -g 'daemon off;'
        volumes:
            - ./nginx.conf:/etc/nginx/conf.d/default.conf
        links:
            - app
        ports:
            - 80:80

volumes:
    nomad_oasis_mongo:
    nomad_oasis_elastic:
    nomad_oasis_rabbitmq:
    nomad_oasis_files:
```

There are no mandatory changes necessary.

A few things to notice:
- All services use docker volumes for storage. This could be changed to host mounts.
- It mounts three configuration files that need to be provided (see below): `nomad.yaml`, `nginx.conf`, `env.js`, `gunicorn.conf`, `gunicorn.log.conf`.
- The only exposed port is `80`. This could be changed to a desired port if necessary.
- The NOMAD images are pulled from our gitlab in Garching, the other services use images from a public registry (*dockerhub*).
- All container will be named `nomad_oasis_*`. These names can be used to later reference the container with the `docker` cmd.
- The NOMAD images we use are tagged `stable`. This could be replaced with concrete version tags.
- The services are setup to restart `always`, you might want to change this to `no` while debugging errors to prevent
indefinite restarts.

### nomad.yaml

NOMAD app and worker read a `nomad.yaml` for configuration.

```yaml
client:
  url: 'http://<your-host>/nomad-oasis/api'

services:
  api_base_path: '/nomad-oasis'
  admin_user_id: '<your admin user id>'

keycloak:
  realm_name: fairdi_nomad_prod
  username: '<your admin username>'
  password: '<your admin user password>'
  oasis: true

mongo:
    db_name: nomad_v0_8

elastic:
    index_name: nomad_v0_8
```

You need to change:
- Replace `your-host` and admin credentials respectively.
- `api_base_path` defines the path under with the app is run. It needs to be changed, if you use a different base path.

A few things to notice:
- Be secretive about your admin credentials; make sure this file is not publicly readable.

### env.js

The GUI also has a config file, called `env.js` with a similar function than `nomad.yaml`.

```js
window.nomadEnv = {
  'appBase': '/nomad-oasis/',
  'keycloakBase': 'https://nomad-lab.eu/fairdi/keycloak/auth/',
  'keycloakRealm': 'fairdi_nomad_prod',
  'keycloakClientId': 'nomad_public',
  'debug': false,
  'oasis': true
};
```

You need to change:
- `appBase` defines the base path again. It needs to be changed, if you use a different base path.

### nginx.conf

The GUI container serves as a proxy that forwards request to the app container. The
proxy is an nginx server and needs a configuration similar to this:

```
server {
    listen        80;
    server_name   <your-host>;
    proxy_set_header Host $host;

    location / {
        proxy_pass http://app:8000;
    }

    location ~ /nomad-oasis\/?(gui)?$ {
        rewrite ^ /nomad-oasis/gui/ permanent;
    }

    location /nomad-oasis/gui/ {
        proxy_intercept_errors on;
        error_page 404 = @redirect_to_index;
        proxy_pass http://app:8000;
    }

    location @redirect_to_index {
        rewrite ^ /nomad-oasis/gui/index.html break;
        proxy_pass http://app:8000;
    }

    location ~ \/gui\/(service-worker\.js|meta\.json)$ {
        add_header Last-Modified $date_gmt;
        add_header Cache-Control 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0';
        if_modified_since off;
        expires off;
        etag off;
        proxy_pass http://app:8000;
    }

    location ~ \/api\/uploads\/?$ {
        client_max_body_size 35g;
        proxy_request_buffering off;
        proxy_pass http://app:8000;
    }

    location ~ \/api\/(raw|archive) {
        proxy_buffering off;
        proxy_pass http://app:8000;
    }

    location ~ \/api\/mirror {
        proxy_buffering off;
        proxy_read_timeout 600;
        proxy_pass http://app:8000;
    }
}
```

You need to change:
- Replace `<your-host>`

A few things to notice:
- It configures the base path (`nomad-oasis`) at multiple places. It needs to be changed, if you use a different base path.
- You can use the server to server additional content if you like.
- `client_max_body_size` sets a limit to the possible upload size.
- If you operate the GUI container behind another proxy, keep in mind that your proxy should not buffer requests/responses to allow streaming of large requests/responses for `../api/uploads` and `../api/raw`.

### gunicorn

Simply create empty `gunicorn.conf` and `gunicorn.log.conf` in the beginning. Gunicorn
is the WSGI-server that runs the nomad app. Consult the [gunicorn documentation](https://docs.gunicorn.org/en/stable/configure.html)
for configuration options.

## Starting and stopping

If you prepared the above files, simply use the usual `docker-compose` commands to start everything.
In the beginning and for debugging problems, it is recommended to start services separately:
```
docker-compose up -d mongodb elastic rabbitmq
docker-compose up app worker gui
```

The `-d` option runs container in the background as *daemons*. Later you can run all at once:
```
docker-compose up -d
```

You can also use docker to stop and remove faulty containers that run as *daemons*:
```
docker stop nomad_oasis_app
docker rm nomad_oasis_app
```

If everything works, the gui should be available under:
```
http://<your host>/nomad-oasis/gui/
```

If you run into troubles, use the dev-tools of you browser to check the javascript logs
or monitor the network traffic for HTTP 500/400/404/401 responses.

To see if at least the api works, check
```
http://<your host>/nomad-oasis/alive
http://<your host>/nomad-oasis/api/info
```

To see logs or 'go into' a running container, you can access the individual containers
with their names and the usual docker commands:

```
docker logs nomad_oasis_app
```

```
docker exec -ti nomad_oasis_app /bin/bash
```

If you want to report problems with your OASIS. Please provide the logs for
- nomad_oasis_app
- nomad_oasis_worker
- nomad_oasis_gui

## Migrating from an older version (0.7.x to 0.8.x)

Between versions 0.7.x and 0.8.x we needed to change how archive and metadata data is stored
internally in files and databases. This means you cannot simply start a new version of
NOMAD on top of the old data. But there is a strategy to adapt the data.

First, shutdown the OASIS and remove all old container.
```
docker-compose stop
docker-compose rm -f
```

Update you config files (`docker-compose.yaml`, `nomad.yaml`, `env.js`, `nginx.conf`) according
to the latest documentation (see above). Especially make sure to select a new name for
databases and search index in your `nomad.yaml` (e.g. `nomad_v0_8`). This will
allow us to create new data while retaining the old, i.e. to copy the old data over.

Make sure you get the latest images and start the OASIS with the new version of NOMAD:
```
docker-compose pull
docker-compose up -d
```

If you go to the GUI of your OASIS, it should now show the new version and appear empty,
because we are using a different database and search index now.

To migrate the data, we created a command that you can run within your OASIS' NOMAD
application container. This command takes the old database name as argument, it will copy
all data over and then reprocess the data to create data in the new archive format and
populate the search index. The default database name in version 0.7.x installations was `nomad_fairdi`.
Be patient.

```
docker exec -ti nomad_oasis_app bash -c 'nomad admin migrate --mongo-db nomad_fairdi'
```

Now all your data should appear in your OASIS again. If you like, you can remove the
old index and database:

```
docker exec nomad_oasis_elastic bash -c 'curl -X DELETE http://elastic:9200/nomad_fairdi'
docker exec nomad_oasis_mongo bash -c 'mongo nomad_fairdi --eval "printjson(db.dropDatabase())"'
```

## NOMAD Oasis FAQ

### Why use an Oasis?
There are three reasons: You want to manage data in private, you want local availability of public NOMAD data without network restrictions, or you want to manage large amounts of low quality and preliminary data that is not intended for publication.

### How to organize data in NOMAD Oasis?

#### How can I categorize or label my data?
Current, NOMAD supports the following mechanism to organize data:
data always belongs to one upload, one uploading user, and is assigned an upload datetime; uploads can have a custom name
data can be assigned to multiple independent datasets
data can hold a proprietary id called “external_id”
data can be assigned multiple authors in addition to the uploading user
The next NOMAD release (0.8.x) will contain more features to filter data based on uploader and upload time. It will also include a revised search bar that makes it easier to filter for external_id or upload_name.

####  Is there some rights-based visibility?
No. Currently, NOMAD only supports uploader controlled visibility. The uploader decides when to make an upload public (with or without embargo). The embargo can be used to limit the visibility of an upload to users that the uploader want to share his upload with.

### How to share data with the central NOMAD?

Keep in mind, it is not entirely clear, how we will do this.

#### How to designate Oasis data for publishing to NOMAD?
Currently, you should use one of the organizational mechanism to designate data for being published to NOMAD. we, you can use a dedicated dataset for publishable data.

#### How to upload?

Will will probably provide functionality in the API of the central NOMAD to upload data from an Oasis to the central NOMAD. We will provide the necessary scripts and detailed instructions. Most likely the data that is uploaded to the central NOMAD can be selected via a search query. Therefore, using a dedicated dataset, would be an easy to select criteria.

### How to maintain an Oasis installation?

#### How to install a NOMAD Oasis?
Follow our guide: https://nomad-lab.eu/prod/rae/docs/ops.html#operating-a-nomad-oasis

#### How do version numbers work?
There are still a lot of thing in NOMAD that are subject to change. Currently, changes in the minor version number (0.x.0) designate major changes that require data migration. Changes in the patch version number (0.7.x) just contain minor changes and fixes and do not require data migration. Once we reach 1.0.0, NOMAD will use the regular semantic versioning conventions.

#### How to upgrade a NOMAD Oasis?
When we release a new version of the NOMAD software, it will be available as a new Docker image with an increased version number. You simply change the version number in your docker-compose.yaml and restart.

#### What about major releases?
Going from NOMAD 0.7.x to 0.8.x will require data migration. This means the layout of the data has changed and the new version cannot be used on top of the old data. This requires a separate installation of the new version and mirroring the data from the old version via NOMAD’s API. Detailed instructions will be made available with the new version.

#### How to move data between installations?
We the release of 0.8.x, we will clarify and how to move data between installations. (See last question)

#### How to backup my Oasis?
To backup your Oasis at least the file data and mongodb data needs to be backed up. You determined the path to your file data (your uploads) during the installation. This directory can be backed up like any other file backup (e.g. rsync). To backup the mongodb, please refer to the official mongodb documentation: https://docs.mongodb.com/manual/core/backups/. We suggest a simple mongodump export that is backed up alongside your files. The elasticsearch contents can be reproduced with the information in files and mongodb.