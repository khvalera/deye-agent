#!/usr/bin/bash

mv locale/deye-agent.pot locale/deye-agent.pot_old
xgettext --language=Python --keyword=_ --package-name=deye-agent --msgid-bugs-address=khvalera@ukr.net --from-code=UTF-8 --output=locale/deye-agent.pot $(find . -name "*.py")
mv locale/uk/LC_MESSAGES/deye-agent.po locale/uk/LC_MESSAGES/deye-agent.po_old
msginit --locale=en_US.UTF-8 --no-translator --input=locale/deye-agent.pot --output-file=locale/en/LC_MESSAGES/deye-agent.po
msginit --locale=uk_UA.UTF-8 --no-translator --input=locale/deye-agent.pot --output-file=locale/uk/LC_MESSAGES/deye-agent.po
#msgmerge --update ./locale/en/LC_MESSAGES/deye-agent.po ./locale/deye-agent.pot
