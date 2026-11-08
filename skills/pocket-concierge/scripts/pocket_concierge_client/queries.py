"""Fixed consumer read queries; no caller-supplied GraphQL or mutations."""

SUMMARY = 'id name realTimeBooking area { id name } cuisines { id name } priceRanges { min max serviceType }'
COURSE = 'id name costPerGuest fixedPrice fixedTitle serviceType summary supplementaryInformation'
QUERIES = {
    'filters': 'query Filters { areas { id name } cuisines { id name } }',
    'search': '''query Search($keyword:String,$areas:[ID!],$cuisines:[ID!],$date:ISO8601Date,
        $people:Int,$meal:[ServiceType!],$min:Int,$max:Int,$instant:Boolean,$page:PaginationInput) {
      venuesSearch(keyword:$keyword,areaIds:$areas,cuisines:$cuisines,date:$date,partySize:$people,
        serviceTypes:$meal,minPricePerPerson:$min,maxPricePerPerson:$max,realTimeBooking:$instant,paginationInput:$page) {
        collection { '''+SUMMARY+''' } metadata { currentPage limitValue totalCount totalPages }
      }
    }''',
    'detail': 'query Detail($id:ID!) { venue(id:$id) { '+SUMMARY+'''
        localizedAddress addressHidden businessHours holidays longDescription nearestStations
        reservationTerms services transactionsAllowed frequentlyAskedQuestions { question answer }
        courses { '''+COURSE+' } } }',
    'calendar': 'query Calendar($id:ID!) { venue(id:$id) { id name realTimeBooking availabilityCalendar { reservationDates waitlistDates } } }',
    'slots': 'query Slots($id:ID!,$date:ISO8601Date!) { venue(id:$id) { id name realTimeBooking courses { id name } } '+'''
      availabilitySearch(venueId:$id,date:$date) {
        __typename
        ... on ReservableAvailability {
          id startTime endTime seatingType minPartySize maxPartySize course { '''+COURSE+''' }
        }
        ... on WaitlistableAvailability {
          startTime endTime minPartySize maxPartySize course { '''+COURSE+''' }
        }
      }
    }''',
}
QUERIES['detail_basic'] = QUERIES['detail'].replace('courses { '+COURSE+' }', '')
QUERIES['courses'] = 'query Courses($id:ID!) { venue(id:$id) { id name realTimeBooking reservationTerms courses { '+COURSE+' } } }'
