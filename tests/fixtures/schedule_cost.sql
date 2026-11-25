CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, created_at REAL, usage TEXT, tool_steps TEXT, status TEXT);
INSERT INTO sessions VALUES ('old','schedule'),('new','schedule'),('shared','schedule'),('web','web');
-- Fixed now=1000000; cutoff=395200, strictly exclusive (same as plan SQL).
INSERT INTO messages VALUES
 (1,'old','assistant',999900,'{"input":1000,"cache":200}','[{},{},{}]','completed'),
 (2,'new','assistant',999950,'{"input":2000,"cache":800}','[{}]','completed'),
 (3,'new','assistant',999960,NULL,'[]','completed'),
 (4,'new','assistant',999970,'broken','broken','completed'),
 (5,'shared','assistant',999980,'{"input":100,"cache":10}','[{},{}]','completed'),
 (6,'shared','assistant',999981,'{"input":900,"cache":90}','[{}]','completed'),
 (7,'shared','assistant',999982,'{"input":700,"cache":70}','[{}]','completed'),
 (8,'new','assistant',999990,'{"input":9999,"cache":9999}','[{}]','running'),
 (9,'new','assistant',999991,'{"input":9999,"cache":9999}','[{}]','pending'),
 (10,'new','assistant',395200,'{"input":9999,"cache":9999}','[{}]','completed'),
 (11,'new','assistant',1000001,'{"input":9999,"cache":9999}','[{}]','completed'),
 (12,'old','assistant',999998,'{"input":50,"cache":0}','[]','completed'),
 (13,'web','assistant',999999,'{"input":9999,"cache":9999}','[{}]','completed'),
 (14,'new','user',999999,'{"input":9999}','[]','completed');
