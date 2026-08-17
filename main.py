# Workiva Zero-Row Hider - OpenShift fixed document ID version
#
# Spreadsheet IDs come from the OpenShift Secret key:
#   WORKIVA_DOCUMENT_IDS
# Format:
#   spreadsheet-id-1,spreadsheet-id-2,spreadsheet-id-3
#
# The worker generates a fresh Workiva bearer token on every run,
# checks the configured control cell, processes the configured
# spreadsheet IDs, and exits. OpenShift CronJob handles scheduling.
#
############################################################################
# Workiva Spreadsheet Zero-Row Hider
#
# Updated for:
#   Workiva API version 2026-01-01
#   OpenShift CronJob
#   EU Workiva environment
#
# Original logic based on Workiva example code.
############################################################################

import decimal
import json
import os
import sys
import time
from enum import Enum

import requests


# ============================================================
# OPENSHIFT ENVIRONMENT VARIABLES
# ============================================================

CLIENT_ID = os.getenv("WORKIVA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("WORKIVA_CLIENT_SECRET", "").strip()

# One comma-separated value containing every spreadsheet ID that
# should have zero rows suppressed.
DOCUMENT_IDS_RAW = os.getenv("WORKIVA_DOCUMENT_IDS", "").strip()

# Location of the TRUE/FALSE control cell.
CONTROL_SPREADSHEET_ID = os.getenv(
    "WORKIVA_CONTROL_SPREADSHEET_ID", ""
).strip()

CONTROL_SHEET_ID = os.getenv(
    "WORKIVA_CONTROL_SHEET_ID", ""
).strip()

# A1 address of the Workiva control cell.
CONTROL_CELL = os.getenv("WORKIVA_CONTROL_CELL", "B2").strip() or "B2"


# ============================================================
# CHECK REQUIRED SETTINGS
# ============================================================

required_settings = {
    "WORKIVA_CLIENT_ID": CLIENT_ID,
    "WORKIVA_CLIENT_SECRET": CLIENT_SECRET,
    "WORKIVA_DOCUMENT_IDS": DOCUMENT_IDS_RAW,
    "WORKIVA_CONTROL_SPREADSHEET_ID": CONTROL_SPREADSHEET_ID,
    "WORKIVA_CONTROL_SHEET_ID": CONTROL_SHEET_ID,
}

missing_settings = [
    name for name, value in required_settings.items() if not value
]

if missing_settings:
    raise RuntimeError(
        "Missing required OpenShift environment variable(s): "
        + ", ".join(missing_settings)
    )


DOCUMENT_IDS = [
    document_id.strip()
    for document_id in DOCUMENT_IDS_RAW.split(",")
    if document_id.strip()
]

if not DOCUMENT_IDS:
    raise RuntimeError(
        "WORKIVA_DOCUMENT_IDS does not contain any spreadsheet IDs."
    )



# ============================================================
# WORKIVA 2026 API SETTINGS
# ============================================================

API_VERSION = os.getenv("WORKIVA_API_VERSION", "2026-01-01").strip()

# EU Workiva environment by default.
BASE_URL = os.getenv(
    "WORKIVA_BASE_URL", "https://api.eu.wdesk.com"
).strip().rstrip("/")

# 2026 API token endpoint
AUTH_URL = f"{BASE_URL}/oauth2/token"

# 2026 spreadsheet endpoint
SS_API_URL = f"{BASE_URL}/spreadsheets"


# ============================================================
# NUMBER PRECISION SETTINGS
# ============================================================

class NumberPrecision(Enum):
    BASIS_POINTS = 0.0001
    HUNDREDTHS = 0.01
    ONES = 1
    THOUSANDS = 1_000
    TEN_THOUSANDS = 10_000
    MILLIONS = 1_000_000
    HUNDRED_MILLIONS = 100_000_000
    BILLIONS = 1_000_000_000
    TRILLIONS = 1_000_000_000_000


# ============================================================
# AUTHENTICATION
# ============================================================

class ApiAuth:

    def __init__(self):

        self.headers = {
            "X-Version": API_VERSION,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }


    def get_auth_token(self):

        print("Authenticating with Workiva...")

        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        }

        try:
            response = requests.post(
                AUTH_URL,
                headers=self.headers,
                data=data,
                timeout=30,
            )

        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not connect to Workiva authentication API:\n{exc}"
            ) from exc


        print(
            "Authentication status:",
            response.status_code
        )


        if not response.ok:

            raise RuntimeError(
                "Workiva authentication failed.\n\n"
                f"HTTP status: {response.status_code}\n"
                f"Response: {response.text}"
            )


        token_data = response.json()

        access_token = token_data.get(
            "access_token"
        )


        if not access_token:

            raise RuntimeError(
                "Authentication returned HTTP 200, "
                "but there was no access_token."
            )


        print("Authentication successful.")

        return access_token


# ============================================================
# WORKIVA SPREADSHEET API
# ============================================================

class SpreadsheetApi:

    def __init__(self, access_token):

        self.headers = {
            "X-Version": API_VERSION,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        self.total_rows_hidden = 0


    # ========================================================
    # GENERAL WORKIVA REQUEST
    # ========================================================

    def request(
        self,
        method,
        url,
        **kwargs,
    ):

        """
        Send a request to Workiva.

        Handles:
        - normal requests
        - temporary 429 rate limits
        - useful error output
        """

        max_attempts = 5

        for attempt in range(
            1,
            max_attempts + 1,
        ):

            try:

                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    timeout=60,
                    **kwargs,
                )

            except requests.RequestException as exc:

                raise RuntimeError(
                    "\nNetwork error while talking to Workiva.\n"
                    f"URL: {url}\n"
                    f"Error: {exc}"
                ) from exc


            # -----------------------------------------------
            # RATE LIMIT
            # -----------------------------------------------

            if response.status_code == 429:

                retry_after = int(
                    response.headers.get(
                        "Retry-After",
                        "5",
                    )
                )

                print(
                    f"Workiva rate limit reached. "
                    f"Waiting {retry_after} seconds..."
                )

                time.sleep(
                    retry_after
                )

                continue


            # -----------------------------------------------
            # WORKIVA ERROR
            # -----------------------------------------------

            if not response.ok:

                request_id = (
                    response.headers.get(
                        "X-Request-ID",
                        "Not provided",
                    )
                )

                raise RuntimeError(
                    "\nWorkiva API returned an error.\n\n"
                    f"Method: {method}\n"
                    f"URL: {url}\n"
                    f"HTTP status: {response.status_code}\n"
                    f"X-Request-ID: {request_id}\n\n"
                    f"Response:\n{response.text}"
                )


            return response


        raise RuntimeError(
            "Workiva request failed repeatedly "
            "because of rate limiting."
        )


    # ========================================================
    # WAIT FOR ASYNC WORKIVA OPERATION
    # ========================================================

    def wait_for_operation(
        self,
        response,
    ):

        """
        Workiva 2026 update operations can return HTTP 202.

        That means:
            "I accepted your change, but I am still working on it."

        We therefore poll the Location URL until Workiva says
        the operation has completed.
        """

        if response.status_code != 202:
            return


        operation_url = (
            response.headers.get(
                "Location"
            )
        )


        # Location can also be supplied in JSON
        if not operation_url:

            try:

                operation_url = (
                    response.json().get(
                        "operationLocation"
                    )
                )

            except ValueError:
                operation_url = None


        if not operation_url:

            raise RuntimeError(
                "Workiva returned HTTP 202, but no "
                "operation Location was supplied."
            )


        retry_after = int(
            response.headers.get(
                "Retry-After",
                "2",
            )
        )


        while True:

            time.sleep(
                retry_after
            )


            operation_response = self.request(
                "GET",
                operation_url,
            )


            operation = (
                operation_response.json()
            )


            status = (
                operation.get(
                    "status",
                    ""
                )
                .lower()
            )


            if status in (
                "completed",
                "succeeded",
                "success",
            ):

                return operation


            if status in (
                "failed",
                "error",
                "cancelled",
                "canceled",
            ):

                raise RuntimeError(
                    "Workiva asynchronous operation failed.\n\n"
                    + json.dumps(
                        operation,
                        indent=2,
                    )
                )


            retry_after = int(
                operation_response.headers.get(
                    "Retry-After",
                    "2",
                )
            )


    # ========================================================
    # TEST CONNECTION
    # ========================================================

    def test_connection(
        self,
        document_id,
    ):

        print(
            "\nTesting connection to spreadsheet..."
        )


        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets"
        )


        response = self.request(
            "GET",
            url,
        )


        data = response.json()

        sheets = data.get(
            "data",
            []
        )


        print(
            f"Connection successful."
        )

        print(
            f"Found {len(sheets)} sheet(s) "
            f"in first response."
        )


        return sheets


    # ========================================================
    # READ / WRITE CONTROL CELL
    # ========================================================

    def get_cell_value(
        self,
        document_id,
        table_id,
        cell_range,
    ):

        """
        Read a single Workiva cell using A1 notation.

        Example:
            cell_range = "B2"
        """

        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets/"
            f"{table_id}/values/"
            f"{cell_range}"
        )

        response = self.request(
            "GET",
            url,
            params={
                "$valuestyle": "calculated",
            },
        )

        result = response.json()
        data = result.get("data", [])

        if not data:
            return None

        range_result = data[0]
        values = range_result.get("values", [])

        if not values or not values[0]:
            return None

        return values[0][0]


    def set_cell_value(
        self,
        document_id,
        table_id,
        cell_range,
        value,
    ):

        """
        Write a single value to a Workiva cell using A1 notation.
        Workiva may process this asynchronously, so wait for it.
        """

        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets/"
            f"{table_id}/values/"
            f"{cell_range}"
        )

        payload = {
            "values": [
                [value]
            ]
        }

        response = self.request(
            "PUT",
            url,
            json=payload,
        )

        self.wait_for_operation(
            response
        )


    # ========================================================
    # GET ALL SHEETS
    # ========================================================

    def get_document_tables(
        self,
        document_id,
    ):

        """
        Retrieve every sheet ID.

        Supports Workiva's 2026 pagination.
        """

        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets"
        )


        sheet_ids = []


        while url:

            response = self.request(
                "GET",
                url,
            )


            result = (
                response.json()
            )


            for sheet in result.get(
                "data",
                []
            ):

                sheet_ids.append(
                    sheet["id"]
                )


            url = result.get(
                "@nextLink"
            )


        return sheet_ids


    # ========================================================
    # GET SHEET DATA
    # ========================================================

    def get_table_data(
        self,
        document_id,
        table_id,
    ):

        """
        Retrieve sheet cells using Workiva 2026 API.

        The 2026 API can paginate large sheets, so we follow
        @nextLink until all available cell data is retrieved.
        """

        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets/"
            f"{table_id}/sheetdata"
        )


        all_cells = []


        params = {
            "$maxcellsperpage": 50000,
            "$fields": (
                "cells.calculatedValue,"
                "cells.formats.valueFormat,"
                "cells.effectiveFormats.valueFormat"
            ),
        }


        first_request = True


        while url:

            response = self.request(
                "GET",
                url,
                params=(
                    params
                    if first_request
                    else None
                ),
            )


            first_request = False


            result = response.json()

            data = result.get(
                "data",
                {}
            )


            cells = data.get(
                "cells",
                []
            )


            all_cells.extend(
                cells
            )


            url = result.get(
                "@nextLink"
            )


        return all_cells


    # ========================================================
    # HIDE SPECIFIC ROWS
    # ========================================================

    def hide_table_rows(
        self,
        document_id,
        table_id,
        row_indices,
    ):

        if not row_indices:
            return


        row_indices = sorted(
            set(row_indices)
        )


        self.total_rows_hidden += len(
            row_indices
        )


        # -----------------------------------------------
        # Convert:
        #
        # [2, 3, 4, 8, 9]
        #
        # into:
        #
        # 2-4
        # 8-9
        # -----------------------------------------------

        intervals = []


        start_index = row_indices[0]
        end_index = row_indices[0]


        for index in row_indices[1:]:

            if index > end_index + 1:

                intervals.append(
                    {
                        "start": start_index,
                        "end": end_index,
                    }
                )

                start_index = index


            end_index = index


        intervals.append(
            {
                "start": start_index,
                "end": end_index,
            }
        )


        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets/"
            f"{table_id}/update"
        )


        payload = {
            "hideRows": {
                "intervals": intervals
            }
        }


        response = self.request(
            "POST",
            url,
            json=payload,
        )


        self.wait_for_operation(
            response
        )


    # ========================================================
    # UNHIDE ALL ROWS
    # ========================================================

    def unhide_table_rows(
        self,
        document_id,
        table_id,
    ):

        url = (
            f"{SS_API_URL}/"
            f"{document_id}/sheets/"
            f"{table_id}/update"
        )


        payload = {
            "unhideRows": {
                "intervals": [
                    {}
                ]
            }
        }


        response = self.request(
            "POST",
            url,
            json=payload,
        )


        self.wait_for_operation(
            response
        )


    # ========================================================
    # CONVERT VALUES TO DISPLAYED VALUES
    # ========================================================

    def get_rows_as_displayed(
        self,
        document_id,
        table_id,
    ):

        rows_as_displayed = []


        table_data = (
            self.get_table_data(
                document_id,
                table_id,
            )
        )


        for row in table_data:

            displayed_row = []


            for cell in row:

                calculated_value = (
                    cell.get(
                        "calculatedValue"
                    )
                )


                # -------------------------------------------
                # Try converting numbers to Decimal
                # -------------------------------------------

                if not isinstance(
                    calculated_value,
                    decimal.Decimal,
                ):

                    try:

                        calculated_value = (
                            decimal.Decimal(
                                str(
                                    calculated_value
                                )
                            )
                        )

                    except (
                        decimal.InvalidOperation,
                        ValueError,
                        TypeError,
                    ):

                        pass


                displayed_value = (
                    calculated_value
                )


                # -------------------------------------------
                # Apply Workiva display scaling
                # -------------------------------------------

                if isinstance(
                    displayed_value,
                    decimal.Decimal,
                ):


                    # First try regular formats.
                    formats = cell.get(
                        "formats",
                        {}
                    )


                    value_format = (
                        formats.get(
                            "valueFormat",
                            {}
                        )
                    )


                    # 2026 responses may expose effective formats.
                    if not value_format:

                        effective_formats = (
                            cell.get(
                                "effectiveFormats",
                                {}
                            )
                        )

                        value_format = (
                            effective_formats.get(
                                "valueFormat",
                                {}
                            )
                        )


                    shown_in = (
                        value_format.get(
                            "shownIn"
                        )
                    )


                    if shown_in:

                        precision_name = (
                            shown_in.replace(
                                " ",
                                "_"
                            )
                        )


                        if (
                            precision_name
                            in NumberPrecision.__members__
                        ):

                            scale = (
                                NumberPrecision[
                                    precision_name
                                ].value
                            )


                            displayed_value /= (
                                decimal.Decimal(
                                    str(scale)
                                )
                            )


                    precision = (
                        value_format.get(
                            "precision"
                        )
                    )


                    if (
                        precision
                        and not precision.get(
                            "auto",
                            True,
                        )
                    ):

                        precision_value = (
                            precision.get(
                                "value",
                                0,
                            )
                        )


                        displayed_value = (
                            displayed_value.quantize(
                                decimal.Decimal(10)
                                ** precision_value,
                                rounding=(
                                    decimal
                                    .ROUND_HALF_UP
                                ),
                            )
                        )


                displayed_row.append(
                    displayed_value
                )


            rows_as_displayed.append(
                displayed_row
            )


        return rows_as_displayed


    # ========================================================
    # DETERMINE SECTION ROWS TO HIDE
    # ========================================================

    def section_rows_to_hide(
        self,
        start_row,
        stop_row,
        zero_rows,
        has_numeric_data,
        has_non_zero_numeric_data,
    ):

        if has_non_zero_numeric_data:
            return zero_rows


        if has_numeric_data:

            return list(
                range(
                    start_row,
                    stop_row + 1,
                )
            )


        return []


    # ========================================================
    # FIND ZERO ROWS
    # ========================================================

    def find_rows_to_hide(
        self,
        rows,
    ):

        rows_to_hide = []


        title_row = None
        zero_rows = []

        has_numeric_data = False

        has_non_zero_numeric_data = False


        for row_index, row in enumerate(
            rows
        ):


            is_spacer_row = True
            has_numbers = False
            all_zeroes = True


            for cell in row:


                if cell not in (
                    None,
                    "",
                ):

                    is_spacer_row = False


                if isinstance(
                    cell,
                    decimal.Decimal,
                ):

                    has_numbers = True


                    if cell != 0:

                        all_zeroes = False

                        break


            # -----------------------------------------------
            # Blank row means end of section
            # -----------------------------------------------

            if is_spacer_row:


                if title_row is not None:

                    rows_to_hide.extend(
                        self.section_rows_to_hide(
                            title_row,
                            row_index,
                            zero_rows,
                            has_numeric_data,
                            has_non_zero_numeric_data,
                        )
                    )


                    title_row = None

                    zero_rows = []

                    has_numeric_data = False

                    has_non_zero_numeric_data = False


            else:


                if title_row is None:

                    title_row = (
                        row_index
                    )


                if has_numbers:

                    has_numeric_data = True


                    if all_zeroes:

                        zero_rows.append(
                            row_index
                        )

                    else:

                        has_non_zero_numeric_data = True


        # -----------------------------------------------
        # Handle final section if sheet does not end
        # with blank row
        # -----------------------------------------------

        if title_row is not None:


            last_row_index = (
                len(rows) - 1
            )


            rows_to_hide.extend(
                self.section_rows_to_hide(
                    title_row,
                    last_row_index,
                    zero_rows,
                    has_numeric_data,
                    has_non_zero_numeric_data,
                )
            )


        return sorted(
            set(rows_to_hide)
        )


    # ========================================================
    # HIDE ZERO ROWS ACROSS ALL SHEETS
    # ========================================================

    def hide_rows(
        self,
        document_id,
    ):


        table_ids = (
            self.get_document_tables(
                document_id
            )
        )


        print(
            f"\nFound "
            f"{len(table_ids)} sheets."
        )


        for number, table_id in enumerate(
            table_ids,
            start=1,
        ):


            print(
                f"\nProcessing sheet "
                f"{number}/"
                f"{len(table_ids)}"
            )


            print(
                f"Sheet ID: {table_id}"
            )


            rows = (
                self.get_rows_as_displayed(
                    document_id,
                    table_id,
                )
            )


            rows_to_hide = (
                self.find_rows_to_hide(
                    rows
                )
            )


            print(
                f"Rows examined: "
                f"{len(rows)}"
            )


            print(
                f"Rows to hide: "
                f"{len(rows_to_hide)}"
            )


            if rows_to_hide:

                self.hide_table_rows(
                    document_id,
                    table_id,
                    rows_to_hide,
                )


                print(
                    "Rows hidden successfully."
                )

            else:

                print(
                    "Nothing to hide."
                )


        print(
            "\n================================="
        )

        print(
            f"TOTAL ROWS HIDDEN: "
            f"{self.total_rows_hidden}"
        )

        print(
            "================================="
        )


    # ========================================================
    # UNHIDE EVERYTHING
    # ========================================================

    def unhide_all_rows(
        self,
        document_id,
    ):


        table_ids = (
            self.get_document_tables(
                document_id
            )
        )


        print(
            f"\nUnhiding rows in "
            f"{len(table_ids)} sheets..."
        )


        for number, table_id in enumerate(
            table_ids,
            start=1,
        ):


            print(
                f"Unhiding sheet "
                f"{number}/"
                f"{len(table_ids)}..."
            )


            self.unhide_table_rows(
                document_id,
                table_id,
            )


        print(
            "All rows have been unhidden."
        )


# ============================================================
# CONTROL FLAG HELPERS
# ============================================================

def normalize_boolean(value):

    """
    Convert Workiva TRUE/FALSE values into Python booleans.
    """

    if isinstance(value, bool):
        return value

    if isinstance(value, str):

        normalized = value.strip().upper()

        if normalized == "TRUE":
            return True

        if normalized == "FALSE":
            return False

    return None


# ============================================================
# PROCESS ALL TARGET SPREADSHEETS
# ============================================================

def suppress_zeros_for_documents(
    spreadsheet_api,
    document_ids,
):

    total_documents = len(document_ids)

    for number, document_id in enumerate(
        document_ids,
        start=1,
    ):

        print("\n\n")
        print("###########################################")
        print(
            f"SPREADSHEET {number}/{total_documents}"
        )
        print(
            f"Spreadsheet ID: {document_id}"
        )
        print("###########################################")

        # Reset the per-spreadsheet counter.
        spreadsheet_api.total_rows_hidden = 0

        # Make sure we can access this spreadsheet.
        spreadsheet_api.test_connection(
            document_id
        )

        # Always start clean: reveal previously hidden rows.
        print(
            "\nSTEP 1: Unhide existing hidden rows"
        )

        spreadsheet_api.unhide_all_rows(
            document_id
        )

        # Re-read all sheets and suppress the current zero rows.
        print(
            "\nSTEP 2: Find and hide zero rows"
        )

        spreadsheet_api.hide_rows(
            document_id
        )

        print(
            f"\nSpreadsheet {number}/{total_documents} completed successfully."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("===========================================")
    print("WORKIVA ZERO ROW HIDER - MULTI SPREADSHEET")
    print(f"API version: {API_VERSION}")
    print(f"Python platform: {sys.platform}")
    print(f"Requests version: {requests.__version__}")
    print("===========================================")

    # --------------------------------------------------------
    # 1. Authenticate once
    # --------------------------------------------------------

    auth_token = (
        ApiAuth()
        .get_auth_token()
    )

    # --------------------------------------------------------
    # 2. Create one reusable Spreadsheet API client
    # --------------------------------------------------------

    spreadsheet_api = (
        SpreadsheetApi(
            auth_token
        )
    )

    # --------------------------------------------------------
    # 3. Read the TRUE/FALSE control cell
    # --------------------------------------------------------

    print("\nChecking zero-suppression control cell...")
    print(f"Control spreadsheet: {CONTROL_SPREADSHEET_ID}")
    print(f"Control sheet: {CONTROL_SHEET_ID}")
    print(f"Control cell: {CONTROL_CELL}")

    raw_control_value = (
        spreadsheet_api.get_cell_value(
            CONTROL_SPREADSHEET_ID,
            CONTROL_SHEET_ID,
            CONTROL_CELL,
        )
    )

    control_value = normalize_boolean(
        raw_control_value
    )

    print(
        f"Control value returned by Workiva: "
        f"{raw_control_value!r}"
    )

    # --------------------------------------------------------
    # 4. TRUE means there is nothing to do
    # --------------------------------------------------------

    if control_value is True:

        print(
            "\nControl cell is TRUE."
        )

        print(
            "No zero-suppression run has been requested."
        )

        print(
            "Change the control cell to FALSE to trigger the next run."
        )

        return

    # --------------------------------------------------------
    # 5. Only FALSE is allowed to trigger the process
    # --------------------------------------------------------

    if control_value is not False:

        raise RuntimeError(
            "The control cell must contain TRUE or FALSE.\n"
            f"Current value: {raw_control_value!r}"
        )

    print("\n===========================================")
    print("CONTROL CELL IS FALSE - STARTING RUN")
    print("===========================================")

    # --------------------------------------------------------
    # 6. Process every spreadsheet ID
    # --------------------------------------------------------
    #
    # IMPORTANT:
    # If any spreadsheet fails, the exception stops the run and
    # the control cell stays FALSE. This makes the failed run
    # visible and prevents us from incorrectly marking it done.
    # --------------------------------------------------------

    suppress_zeros_for_documents(
        spreadsheet_api,
        DOCUMENT_IDS,
    )

    # --------------------------------------------------------
    # 7. All spreadsheets succeeded -> reset FALSE to TRUE
    # --------------------------------------------------------

    print("\n===========================================")
    print("ALL SPREADSHEETS COMPLETED SUCCESSFULLY")
    print("Resetting control cell to TRUE...")
    print("===========================================")

    spreadsheet_api.set_cell_value(
        CONTROL_SPREADSHEET_ID,
        CONTROL_SHEET_ID,
        CONTROL_CELL,
        True,
    )

    print("\nControl cell reset to TRUE successfully.")
    print("Done.")


# ============================================================
# OPENSHIFT CRONJOB ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    # OpenShift CronJob handles the schedule. This process performs
    # exactly one control-cell check and then exits.
    #
    # Any exception is intentionally allowed to terminate the process
    # with a non-zero exit code, so OpenShift records the Job as failed.
    # The Workiva control flag remains FALSE when processing fails.
    main()
