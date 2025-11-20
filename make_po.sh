#!/usr/bin/bash

mv deye-agent/locale/deye-agent.pot deye-agent/locale/deye-agent.pot_old
xgettext --language=Python --keyword=_ --package-name=deye-agent --msgid-bugs-address=khvalera@ukr.net --from-code=UTF-8 --output=deye-agent/locale/deye-agent.pot $(find . -name "*.py")
mv deye-agent/locale/uk/LC_MESSAGES/deye-agent.po deye-agent/locale/uk/LC_MESSAGES/deye-agent.po_old
msginit --locale=en_US.UTF-8 --no-translator --input=deye-agent/locale/deye-agent.pot --output-file=deye-agent/locale/en/LC_MESSAGES/deye-agent.po
msginit --locale=uk_UA.UTF-8 --no-translator --input=deye-agent/locale/deye-agent.pot --output-file=deye-agent/locale/uk/LC_MESSAGES/deye-agent.po
#msgmerge --update ./deye-agent/locale/en/LC_MESSAGES/deye-agent.po ./deye-agent/locale/deye-agent.pot
