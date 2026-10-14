"""Only formulas deliberately written by server code or its fixed PI template.
User-entered names, notes, SKUs and filenames remain literal Excel strings.
"""


def formula(sheet, coordinate, expression):
    sheet[coordinate]=expression
    allowed=getattr(sheet,'_server_formulas',set())
    allowed.add((coordinate,expression))
    sheet._server_formulas=allowed


def trust_template(book):
    for sheet in book:
        sheet._server_formulas={(cell.coordinate,cell.value) for row in sheet for cell in row if cell.data_type=='f'}
    return book


def prepare(book):
    for sheet in book:
        allowed=getattr(sheet,'_server_formulas',set())
        for row in sheet:
            for cell in row:
                if cell.data_type=='f' and (cell.coordinate,cell.value) not in allowed:
                    cell.data_type='s'
    return book
