PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE inventory (
        item TEXT PRIMARY KEY,
        stock INTEGER NOT NULL CHECK (stock >= 0));
INSERT INTO inventory VALUES('WidgetA',15);
INSERT INTO inventory VALUES('WidgetB',10);
INSERT INTO inventory VALUES('GadgetX',5);
INSERT INTO inventory VALUES('FakeItem',0);
CREATE TABLE sources (
        source_id TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL UNIQUE,
        original_name TEXT NOT NULL,
        format TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        parser_version TEXT,
        extracted_text TEXT,
        created_at TEXT NOT NULL);
INSERT INTO sources VALUES('src-7308ab3d7ff26ee3','7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1','invoice_1001.txt','txt',273,'txt-2',NULL,'2026-11-02T13:33:20.637653Z');
INSERT INTO sources VALUES('src-41e4bb0f120f5f7b','41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9','valid_10000_01.json','json',504,'json-1',NULL,'2026-11-02T13:33:20.657741Z');
CREATE TABLE invoices (
        invoice_id TEXT PRIMARY KEY,
        vendor_key TEXT NOT NULL,
        invoice_number_key TEXT NOT NULL,
        current_version INTEGER,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (vendor_key, invoice_number_key));
INSERT INTO invoices VALUES('inv-cb2fdf70e5f647e08dccf4003e2d7836','widgets inc.','1001',1,'paid_mock','2026-11-02T13:33:20.643893Z','2026-11-02T13:33:20.655228Z');
INSERT INTO invoices VALUES('inv-9cfb09329d2d414182b5463b8327f03a','threshold test supply','TH1000001',1,'awaiting_human_approval','2026-11-02T13:33:20.663790Z','2026-11-02T13:33:20.680919Z');
CREATE TABLE invoice_versions (
        version_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        parent_version INTEGER,
        origin TEXT NOT NULL,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        semantic_hash TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (invoice_id, version));
INSERT INTO invoice_versions VALUES('ver-d068a746fd0342edad6afae4fcc3b365','inv-cb2fdf70e5f647e08dccf4003e2d7836',1,NULL,'extracted','src-7308ab3d7ff26ee3','dc3ce91c6146de4fa2d316f5f90054d1e77bb567baefc91c72d68730ea5c1686','{"source_id":"src-7308ab3d7ff26ee3","vendor_name":"Widgets Inc.","vendor_key":"widgets inc.","invoice_number":"INV-1001","invoice_number_key":"1001","revision":null,"invoice_date":"2026-01-15","due_date":"2026-02-01","currency":"USD","payment_terms":"Net 15","notes":null,"lines":[{"item":"WidgetA","quantity":"10","unit_price":"250.00","line_total":null,"note":null,"evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:9","snippet":"WidgetA    qty: 10    unit price: $250.00"}]},{"item":"WidgetB","quantity":"5","unit_price":"500.00","line_total":null,"note":null,"evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:10","snippet":"WidgetB    qty: 5     unit price: $500.00"}]}],"stated":{"subtotal":"5000.00","tax_rate":"0","tax":"0.00","shipping":null,"total":"5000.00"},"computed":null,"normalization_events":[{"field":"invoice_number","raw_value":"INV-1001","normalized_value":"1001","evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:4","snippet":"Invoice Number: INV-1001"}],"provenance":"rule:invoice_number_format"},{"field":"currency","raw_value":null,"normalized_value":"USD","evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:12","snippet":"Subtotal: $5,000.00"}],"provenance":"rule:dataset_usd_assumption"}]}','2026-11-02T13:33:20.644475Z');
INSERT INTO invoice_versions VALUES('ver-c3f380cc21744cb79398f45eb130971f','inv-9cfb09329d2d414182b5463b8327f03a',1,NULL,'extracted','src-41e4bb0f120f5f7b','42d472f80c24720e3f7f4015acaf72bcde28df91cfe496fa11b479935273e81c','{"source_id":"src-41e4bb0f120f5f7b","vendor_name":"Threshold Test Supply","vendor_key":"threshold test supply","invoice_number":"TH-10000-01","invoice_number_key":"TH1000001","revision":null,"invoice_date":"2026-01-29","due_date":"2026-02-28","currency":"USD","payment_terms":"Net 30","notes":null,"lines":[{"item":"WidgetA","quantity":"15","unit_price":"250.00","line_total":null,"note":null,"evidence":[{"source_id":"src-41e4bb0f120f5f7b","location":"$.line_items[0]","snippet":null}]},{"item":"WidgetB","quantity":"10","unit_price":"500.00","line_total":null,"note":null,"evidence":[{"source_id":"src-41e4bb0f120f5f7b","location":"$.line_items[1]","snippet":null}]},{"item":"GadgetX","quantity":"1","unit_price":"750.00","line_total":null,"note":null,"evidence":[{"source_id":"src-41e4bb0f120f5f7b","location":"$.line_items[2]","snippet":null}]}],"stated":{"subtotal":"9500.00","tax_rate":"0.0","tax":"0.00","shipping":"500.01","total":"10000.01"},"computed":null,"normalization_events":[{"field":"invoice_number","raw_value":"TH-10000-01","normalized_value":"TH1000001","evidence":[{"source_id":"src-41e4bb0f120f5f7b","location":"$.invoice_number","snippet":"TH-10000-01"}],"provenance":"rule:invoice_number_format"}]}','2026-11-02T13:33:20.664188Z');
CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        invoice_id TEXT REFERENCES invoices(invoice_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        mode TEXT NOT NULL,
        status TEXT NOT NULL,
        stage TEXT,
        error_code TEXT,
        error_message TEXT,
        retry_of TEXT REFERENCES runs(run_id),
        mode_switch_of TEXT REFERENCES runs(run_id),
        prior_run_id TEXT REFERENCES runs(run_id),
        evaluation_date TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT);
INSERT INTO runs VALUES('run-7b57f9e9610f491d92f4f9cdf3a1c6c9','src-7308ab3d7ff26ee3','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','offline','paid_mock','paid_mock',NULL,NULL,NULL,NULL,NULL,'2026-01-31','2026-11-02T13:33:20.638909Z','2026-11-02T13:33:20.655020Z');
INSERT INTO runs VALUES('run-42b8ff642e5448a7a88a6a1934ce12e1','src-41e4bb0f120f5f7b','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','offline','awaiting_human_approval','awaiting_human_approval',NULL,NULL,NULL,NULL,NULL,'2026-01-31','2026-11-02T13:33:20.658130Z','2026-11-02T13:33:20.680607Z');
CREATE TABLE findings (
        finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        code TEXT NOT NULL,
        severity TEXT NOT NULL,
        payload_json TEXT NOT NULL);
INSERT INTO findings VALUES(1,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','ver-d068a746fd0342edad6afae4fcc3b365','terms_inconsistent','warning','{"code":"terms_inconsistent","severity":"warning","field":"payment_terms","item":null,"expected":"2026-01-30","observed":"2026-02-01","evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:16","snippet":"Payment Terms: Net 15"}],"resolved":false}');
INSERT INTO findings VALUES(2,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','ver-d068a746fd0342edad6afae4fcc3b365','currency_assumed_usd','info','{"code":"currency_assumed_usd","severity":"info","field":"currency","item":null,"expected":null,"observed":"USD","evidence":[{"source_id":"src-7308ab3d7ff26ee3","location":"line:12","snippet":"Subtotal: $5,000.00"}],"resolved":false}');
CREATE TABLE decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        payload_json TEXT NOT NULL,
        final_decision TEXT NOT NULL CHECK (final_decision IN
            ('approved', 'rejected', 'needs_review', 'awaiting_human_approval')),
        policy_version TEXT NOT NULL,
        mode TEXT NOT NULL,
        created_at TEXT NOT NULL);
INSERT INTO decisions VALUES(1,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','ver-d068a746fd0342edad6afae4fcc3b365','{"initial_recommendation":"approve","critique_summary":"offline simulation: critique agrees; 0 omission(s); high_value=False","critique_issues":[],"revised_recommendation":null,"final_decision":"approved","reasons":["R4_auto_approve"],"policy_version":"2026-11-01.1","mode":"offline","provider":"offline","model":"simulated","prompt_version":null,"model_calls_used":0}','approved','2026-11-01.1','offline','2026-11-02T13:33:20.650073Z');
INSERT INTO decisions VALUES(2,'run-42b8ff642e5448a7a88a6a1934ce12e1','ver-c3f380cc21744cb79398f45eb130971f','{"initial_recommendation":"approve","critique_summary":"offline simulation: critique agrees; 0 omission(s); high_value=True","critique_issues":[],"revised_recommendation":null,"final_decision":"awaiting_human_approval","reasons":["R3_high_value"],"policy_version":"2026-11-01.1","mode":"offline","provider":"offline","model":"simulated","prompt_version":null,"model_calls_used":0}','awaiting_human_approval','2026-11-01.1','offline','2026-11-02T13:33:20.672447Z');
CREATE TABLE corrections (
        correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        from_version INTEGER NOT NULL,
        to_version INTEGER NOT NULL,
        field TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        evidence_location TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, from_version) REFERENCES invoice_versions(invoice_id, version),
        FOREIGN KEY (invoice_id, to_version) REFERENCES invoice_versions(invoice_id, version));
CREATE TABLE human_reviews (
        review_id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        action TEXT NOT NULL,
        reviewer TEXT NOT NULL,
        reason TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, version) REFERENCES invoice_versions(invoice_id, version));
CREATE TABLE payments (
        payment_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(invoice_id),
        version INTEGER NOT NULL,
        run_id TEXT NOT NULL REFERENCES runs(run_id),
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        receipt_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id, version) REFERENCES invoice_versions(invoice_id, version));
INSERT INTO payments VALUES('pay-68085a16267c45c08640c97ef25882ed','inv-cb2fdf70e5f647e08dccf4003e2d7836',1,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','5000.00','USD','rcpt-03f79f9396b1','success','2026-11-02T13:33:20.652209Z');
CREATE TABLE audit_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs(run_id),
        invoice_id TEXT REFERENCES invoices(invoice_id),
        version_id TEXT REFERENCES invoice_versions(version_id),
        stage TEXT NOT NULL,
        event TEXT NOT NULL,
        actor TEXT,
        payload_json TEXT,
        created_at TEXT NOT NULL);
INSERT INTO audit_events VALUES(1,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9',NULL,NULL,'intake','received',NULL,'{"mode": "offline", "mode_switch_of": null, "original_name": "invoice_1001.txt", "retry_of": null, "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "received"}','2026-11-02T13:33:20.639141Z');
INSERT INTO audit_events VALUES(2,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','ingestion','extracted',NULL,'{"codes": ["terms_inconsistent", "currency_assumed_usd"], "issues": [], "mode": "offline", "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "extracted", "version": 1}','2026-11-02T13:33:20.645445Z');
INSERT INTO audit_events VALUES(3,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','validation','validated',NULL,'{"codes": ["terms_inconsistent", "currency_assumed_usd"], "mode": "offline", "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "validated"}','2026-11-02T13:33:20.646284Z');
INSERT INTO audit_events VALUES(4,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','approval','recommendation',NULL,'{"codes": [], "mode": "offline", "recommendation": "approve", "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "validated", "summary": "offline simulation: approve based on 0 blocking or review finding(s)"}','2026-11-02T13:33:20.649439Z');
INSERT INTO audit_events VALUES(5,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','approval','critique',NULL,'{"agrees": true, "high_value": false, "issues": [], "mode": "offline", "omissions": [], "revised_recommendation": null, "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "validated", "summary": "offline simulation: critique agrees; 0 omission(s); high_value=False"}','2026-11-02T13:33:20.649778Z');
INSERT INTO audit_events VALUES(6,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','approval','decision',NULL,'{"final_decision": "approved", "mode": "offline", "policy_version": "2026-11-01.1", "rule_ids": ["R4_auto_approve"], "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "approved"}','2026-11-02T13:33:20.650378Z');
INSERT INTO audit_events VALUES(7,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','payment','payment_succeeded',NULL,'{"amount": "5000.00", "currency": "USD", "receipt_id": "rcpt-03f79f9396b1"}','2026-11-02T13:33:20.652254Z');
INSERT INTO audit_events VALUES(8,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','payment','paid',NULL,'{"amount": "5000.00", "created": true, "currency": "USD", "mode": "offline", "receipt_id": "rcpt-03f79f9396b1", "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "paid_mock"}','2026-11-02T13:33:20.652604Z');
INSERT INTO audit_events VALUES(9,'run-7b57f9e9610f491d92f4f9cdf3a1c6c9','inv-cb2fdf70e5f647e08dccf4003e2d7836','ver-d068a746fd0342edad6afae4fcc3b365','service','finished',NULL,'{"errors": [], "mode": "offline", "source_hash": "7308ab3d7ff26ee338e16ba304e762f0ac90403958d6211cfab36c94eb14dfd1", "status": "paid_mock"}','2026-11-02T13:33:20.655378Z');
INSERT INTO audit_events VALUES(10,'run-42b8ff642e5448a7a88a6a1934ce12e1',NULL,NULL,'intake','received',NULL,'{"mode": "offline", "mode_switch_of": null, "original_name": "valid_10000_01.json", "retry_of": null, "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "received"}','2026-11-02T13:33:20.658338Z');
INSERT INTO audit_events VALUES(11,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','ingestion','extracted',NULL,'{"codes": [], "issues": [], "mode": "offline", "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "extracted", "version": 1}','2026-11-02T13:33:20.665228Z');
INSERT INTO audit_events VALUES(12,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','validation','validated',NULL,'{"codes": [], "mode": "offline", "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "validated"}','2026-11-02T13:33:20.667234Z');
INSERT INTO audit_events VALUES(13,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','approval','recommendation',NULL,'{"codes": [], "mode": "offline", "recommendation": "approve", "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "validated", "summary": "offline simulation: approve based on 0 blocking or review finding(s); total above the 10000.00 high-value threshold"}','2026-11-02T13:33:20.670468Z');
INSERT INTO audit_events VALUES(14,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','approval','critique',NULL,'{"agrees": true, "high_value": true, "issues": [], "mode": "offline", "omissions": [], "revised_recommendation": null, "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "validated", "summary": "offline simulation: critique agrees; 0 omission(s); high_value=True"}','2026-11-02T13:33:20.670682Z');
INSERT INTO audit_events VALUES(15,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','approval','decision',NULL,'{"final_decision": "awaiting_human_approval", "mode": "offline", "policy_version": "2026-11-01.1", "rule_ids": ["R3_high_value"], "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "awaiting_human_approval"}','2026-11-02T13:33:20.674357Z');
INSERT INTO audit_events VALUES(16,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','outcome','waiting',NULL,'{"mode": "offline", "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "awaiting_human_approval"}','2026-11-02T13:33:20.675844Z');
INSERT INTO audit_events VALUES(17,'run-42b8ff642e5448a7a88a6a1934ce12e1','inv-9cfb09329d2d414182b5463b8327f03a','ver-c3f380cc21744cb79398f45eb130971f','service','finished',NULL,'{"errors": [], "mode": "offline", "source_hash": "41e4bb0f120f5f7b1a939d4c02c3fbe686b4b4dbfba8a24168506b6480dbb0f9", "status": "awaiting_human_approval"}','2026-11-02T13:33:20.682610Z');
CREATE TABLE idempotency_keys (
        key TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (key, endpoint));
INSERT INTO sqlite_sequence VALUES('audit_events',17);
INSERT INTO sqlite_sequence VALUES('findings',2);
INSERT INTO sqlite_sequence VALUES('decisions',2);
COMMIT;
PRAGMA user_version=6;
