# Posta LuxOS (luxos-mail) - lehky postovni klient v LSL.
#   luxos-mail                          okno (tri sloupce: schranky, zpravy, zprava)
#   luxos-mail --open UCET SCHRANKA UID okno na dane zprave (akce Otevrit v upozorneni)
#   luxos-mail mailto:adresa            psani zatim neni (faze 2): nabidne webmail / zkopirovani adresy
#   luxos-mail --background             spusti sluzbu na pozadi (luxos-mail-service: IDLE, upozorneni, synchronizace)
#   luxos-mail --discover EMAIL [--no-probe]   nalezeni serveru (JSON; okno ho spousti pri pridani uctu)
#   luxos-mail --oauth-config           stahne client ID pro "Prihlasit se ..." z luxos.lux-ai.cz (JSON; okno)
#   luxos-mail --diagnose-oauth ADRESA [--fresh] [--provider ID]   diagnostika prihlaseni u poskytovatele (zprava
#                                       varianta -> odpoved serveru, bez tokenu; mail_diagnose)
# Testovaci vstupy (JSON na stdout): --test-render SOUBOR.eml, --test-part SOUBOR.eml CESTA VYSTUP,
#   --test-imap SOUBOR (odpovedi IMAP), --test-oauth-providers, --test-oauth-url POSKYTOVATEL PORT EMAIL, --test-words TEXT, --test-date TEXT, --test-charset SADA SOUBOR
load env, json, net
load mail_bytes as mb
load mail_mime as mime
load mail_imap as imap
load mail_discover as discover
load luxos_sys
load mail_store as store
load mail_oauth as oauth
load mail_diagnose as diagnose
load mail_ui as ui

function arg_or(index, fallback):
    if len(args) > index:
        return args[index]
    end
    return fallback
end

function test_imap(path):
    raw = readbytes(path)
    out = []
    pos = 0
    n = len(raw)
    conn = imap.new_conn("test")
    conn["buf"] = raw
    while conn["pos"] < n:
        r = {}
        safe:
            r = imap.read_response(conn, 0, True)
        end
        if len(r) == 0:
            break
        end
        t = imap.resp_tokens(r)
        item = {"tag": r["tag"], "line": imap.first_line(r)}
        if len(t) >= 3 and imap.tstr(t[1]).upper() == "FETCH":
            f = imap.fetch_dict(t)
            d = {"seq": f["SEQ"]}
            for key in f.keys():
                if key == "ENVELOPE":
                    d["envelope"] = imap.envelope(f[key])
                elif key == "BODYSTRUCTURE" or key == "BODY":
                    bs = imap.bodystructure(f[key])
                    d["bodystructure"] = bs
                    d["preview_part"] = imap.preview_part(bs).get("section", "")
                    d["attachments"] = imap.has_attachments(bs)
                elif key == "UID" or key == "RFC822.SIZE":
                    d[key] = imap.tint(f[key], 0)
                elif key == "FLAGS":
                    fl = []
                    for x in imap.tlist(f[key]):
                        fl.append(imap.tstr(x))
                    end
                    d[key] = fl
                elif key != "SEQ":
                    d[key] = imap.tstr(f[key])
                end
            end
            item["fetch"] = d
        elif len(t) >= 1 and imap.tstr(t[0]).upper() == "LIST" and len(t) >= 4:
            item["mailbox"] = imap.mutf7_decode(imap.tstr(t[3]))
        end
        out.append(item)
    end
    return out
end

function main():
    first = arg_or(1, "")
    if first == "--background":
        # sluzba je samostatny program bez GTK (mene pameti)
        return luxos_sys.exec([store.service_binary()])
    elif first == "--discover":
        probe = not ("--no-probe" in args)
        print json.encode(discover.discover(arg_or(2, ""), probe))
        return 0
    elif first == "--diagnose-oauth":
        return diagnose.main(args)
    elif first == "--oauth-config":
        print json.encode(oauth.fetch_remote())
        return 0
    elif first == "--test-oauth-providers":
        out = {}
        for p in oauth.providers().values():
            out[p["id"]] = {"available": len(oauth.available(p["id"])) > 0, "client_id": p["client_id"], "redirect_host": p["redirect_host"],
                            "imap": p["imap"], "smtp": p["smtp"], "auth_url": p["auth_url"], "token_url": p["token_url"],
                            "revoke_url": p["revoke_url"]}
        end
        print json.encode({"providers": out, "remote_due": oauth.remote_due()})
        return 0
    elif first == "--test-oauth-url":
        p = oauth.provider(arg_or(2, ""))
        verifier = oauth.random_token(48)
        print json.encode({"url": oauth.authorize_url(p, Int(arg_or(3, "0")), "STATE", verifier, arg_or(4, "")), "verifier": verifier,
                           "challenge": oauth.challenge(verifier)})
        return 0
    elif first == "--test-render":
        print json.encode(mime.render(readbytes(arg_or(2, ""))))
        return 0
    elif first == "--test-part":
        call writebytes(arg_or(4, "/dev/null"), mime.part_bytes(readbytes(arg_or(2, "")), arg_or(3, "")))
        return 0
    elif first == "--test-imap":
        print json.encode(test_imap(arg_or(2, "")))
        return 0
    elif first == "--test-words":
        print json.encode({"text": mime.decode_words(arg_or(2, "")), "addresses": mime.parse_addresses(mime.decode_words(arg_or(2, "")))})
        return 0
    elif first == "--test-date":
        print mime.parse_date(arg_or(2, ""))
        return 0
    elif first == "--test-charset":
        b = readbytes(arg_or(3, ""))
        print mime.decode_text(b, 0, len(b), arg_or(2, ""))
        return 0
    end
    return ui.main(args)
end

call exit(main())
