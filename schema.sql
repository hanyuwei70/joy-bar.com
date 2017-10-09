drop table if EXISTS places_types;
create table places_types(
    id integer PRIMARY KEY AUTOINCREMENT ,
    name text not NULL,
    desc text DEFAULT NULL
);
drop table if EXISTS places;
create table places( --占地
    id integer PRIMARY KEY ,
    name text not null,
    type int,
    FOREIGN KEY (type) REFERENCES places_types(id)
);
drop table if EXISTS reservations;
create table reservations (
    id integer PRIMARY KEY AUTOINCREMENT ,
    contact text not null,  --联系人信息，JSON存储
    place int not null,
    date TEXT not null,
    hours text not null,
    FOREIGN KEY (place) REFERENCES places(id)
);
drop table if EXISTS users;
create table users(
    id integer PRIMARY KEY ,
    username varchar(30) NOT NULL UNIQUE ,
    password text,
    priv integer
)
