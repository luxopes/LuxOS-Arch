# Posta LuxOS - sluzba na pozadi jako samostatny maly program bez GTK (mene pameti nez okno):
# /usr/lib/luxos-mail/luxos-mail-service, spousti ji `luxos-mail --background` (XDG autostart) nebo okno.
load mail_service as service

call exit(service.main())
